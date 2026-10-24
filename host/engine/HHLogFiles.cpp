#include "engine/HHLogFiles.h"
#include "engine/HHRuntime.h"

//------------------------------------------------------------------------------
HHLogFile::HHLogFile(const std::wstring& wstrPath, const std::wstring& wstrName, uint uiFlags)
	: m_wstrPath(wstrPath), m_wstrName(wstrName), m_uiFlags(uiFlags), m_pFile(NULL), m_bOpenedOnce(false)
{
	InitializeCriticalSection(&m_cs);
	Open();
}

HHLogFile::~HHLogFile()
{
	Close();
	DeleteCriticalSection(&m_cs);
}

void HHLogFile::Open(void)
{
	EnterCriticalSection(&m_cs);
	if(!m_pFile)
	{
		// The first open of a run truncates, later reopens append (as the engine's logs).
		m_pFile = _wfsopen(m_wstrPath.c_str(), m_bOpenedOnce ? L"a" : L"w", _SH_DENYWR);
		m_bOpenedOnce = true;
		if(!m_pFile)
			HHLogError("cannot open log file %s", HHNarrow(m_wstrPath).c_str());
	}
	LeaveCriticalSection(&m_cs);
}

void HHLogFile::Close(void)
{
	EnterCriticalSection(&m_cs);
	if(m_pFile)
	{
		fclose(m_pFile);
		m_pFile = NULL;
	}
	LeaveCriticalSection(&m_cs);
}

void HHLogFile::Write(const char* szPrefix, const TCHAR* format, va_list args)
{
	if(!HHLogFileMgr::Get().IsLoggingEnabled() || !format)
		return;
	std::string strText = HHFormatV(format, args);
	EnterCriticalSection(&m_cs);
	if(m_pFile)
	{
		if(!(m_uiFlags & kDontTimeStamp))
			fprintf(m_pFile, "[%.3f] ", HHSeconds());
		fputs(szPrefix, m_pFile);
		fputs(strText.c_str(), m_pFile);
		if(strText.empty() || strText[strText.size() - 1] != '\n')
			fputc('\n', m_pFile);
		if(!(m_uiFlags & kDontFlushOnWrite))
			fflush(m_pFile);
	}
	LeaveCriticalSection(&m_cs);
	if(m_uiFlags & kWriteToConsole)
		HHLog("%s: %s%s", HHNarrow(m_wstrName).c_str(), szPrefix, strText.c_str());
}

void HHLogFile::Msg(const TCHAR* format, ...)
{
	va_list args;
	va_start(args, format);
	Write("", format, args);
	va_end(args);
}

void HHLogFile::DebugMsg(const TCHAR* format, ...)
{
	va_list args;
	va_start(args, format);
	Write("", format, args);
	va_end(args);
}

void HHLogFile::WarningMsg(const TCHAR* format, ...)
{
	va_list args;
	va_start(args, format);
	Write("WARNING: ", format, args);
	va_end(args);
}

void HHLogFile::ErrorMsg(const TCHAR* format, ...)
{
	va_list args;
	va_start(args, format);
	Write("ERROR: ", format, args);
	va_end(args);
}

void HHLogFile::SetFlags(uint uiFlags) { m_uiFlags = uiFlags; }
uint HHLogFile::GetFlags() const { return m_uiFlags; }
void HHLogFile::SetBufSize(int) {}
LPCWSTR HHLogFile::GetFileName() const { return m_wstrName.c_str(); }
void HHLogFile::Archive(LPCWSTR) {}

//------------------------------------------------------------------------------
HHLogFileMgr::HHLogFileMgr() : m_bEnabled(true)
{
	InitializeCriticalSection(&m_cs);
}

HHLogFileMgr::~HHLogFileMgr()
{
	CloseAll();
	DeleteCriticalSection(&m_cs);
}

HHLogFileMgr& HHLogFileMgr::Get()
{
	// Never destroyed: the DLL can still log from its own static destructors at process exit.
	static HHLogFileMgr* s_pMgr = new HHLogFileMgr();
	return *s_pMgr;
}

void HHLogFileMgr::SetFolder(const std::string& strLogsDir)
{
	m_wstrFolder = HHWiden(strLogsDir);
}

void HHLogFileMgr::EnableLogging(void) { m_bEnabled = true; }
void HHLogFileMgr::DisableLogging(void) { m_bEnabled = false; }
bool HHLogFileMgr::IsLoggingEnabled(void) { return m_bEnabled; }

FILogFile* HHLogFileMgr::GetLog(LPCWSTR wszFileName, uint uiFlags, const TCHAR* szTitleString)
{
	if(!wszFileName)
		return NULL;
	std::wstring name(wszFileName);
	for(size_t i = 0; i < name.size(); ++i)
		if(name[i] == L'/')
			name[i] = L'\\';
	std::wstring key(name);
	for(size_t i = 0; i < key.size(); ++i)
		key[i] = (wchar_t)towlower(key[i]);

	EnterCriticalSection(&m_cs);
	LogMap::iterator it = m_logs.find(key);
	HHLogFile* pLog = NULL;
	if(it != m_logs.end())
	{
		pLog = it->second;
	}
	else
	{
		std::wstring path = m_wstrFolder + name;
		size_t slash = path.find_last_of(L'\\');
		if(slash != std::wstring::npos)
			HHEnsureDirectory(HHNarrow(path.substr(0, slash)));
		pLog = new HHLogFile(path, name, uiFlags);
		m_logs[key] = pLog;
		if(szTitleString && *szTitleString)
			pLog->Msg("%s", szTitleString);
	}
	LeaveCriticalSection(&m_cs);
	return pLog;
}

FILogFile* HHLogFileMgr::GetLog(LPCSTR szFileName, uint uiFlags, const TCHAR* szTitleString)
{
	if(!szFileName)
		return NULL;
	return GetLog(HHWiden(szFileName, CP_ACP).c_str(), uiFlags, szTitleString);
}

bool HHLogFileMgr::DeleteLog(FILogFile* pLog)
{
	bool bFound = false;
	EnterCriticalSection(&m_cs);
	for(LogMap::iterator it = m_logs.begin(); it != m_logs.end(); ++it)
	{
		if(it->second == pLog)
		{
			delete it->second;
			m_logs.erase(it);
			bFound = true;
			break;
		}
	}
	LeaveCriticalSection(&m_cs);
	return bFound;
}

bool HHLogFileMgr::DeleteLog(LPCWSTR wszFileName)
{
	if(!wszFileName)
		return false;
	std::wstring key(wszFileName);
	for(size_t i = 0; i < key.size(); ++i)
		key[i] = (wchar_t)towlower(key[i] == L'/' ? L'\\' : key[i]);
	bool bFound = false;
	EnterCriticalSection(&m_cs);
	LogMap::iterator it = m_logs.find(key);
	if(it != m_logs.end())
	{
		delete it->second;
		m_logs.erase(it);
		bFound = true;
	}
	LeaveCriticalSection(&m_cs);
	return bFound;
}

size_t HHLogFileMgr::GetLogCount()
{
	EnterCriticalSection(&m_cs);
	size_t n = m_logs.size();
	LeaveCriticalSection(&m_cs);
	return n;
}

void HHLogFileMgr::CloseAll()
{
	// Files are closed but the objects stay: the DLL may hold FILogFile pointers in statics.
	EnterCriticalSection(&m_cs);
	for(LogMap::iterator it = m_logs.begin(); it != m_logs.end(); ++it)
		it->second->Close();
	LeaveCriticalSection(&m_cs);
}
