#include "engine/HHLogFiles.h"
#include "engine/HHRuntime.h"

//------------------------------------------------------------------------------
HHLogFile::HHLogFile(const std::wstring& wstrPath, const std::wstring& wstrName, uint uiFlags)
	: m_wstrPath(wstrPath), m_wstrName(wstrName), m_uiFlags(uiFlags), m_hFile(INVALID_HANDLE_VALUE), m_bOpenedOnce(false)
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
	if(m_hFile == INVALID_HANDLE_VALUE)
	{
		// The first open of a run truncates, later reopens append (as the engine's logs). Win32
		// handles, not CRT FILE streams: AI logging opens hundreds of files per game and the CRT
		// stream table (512, shared with the DLL) ran out at about turn 100.
		m_hFile = CreateFileW(m_wstrPath.c_str(), m_bOpenedOnce ? FILE_APPEND_DATA : GENERIC_WRITE, FILE_SHARE_READ, NULL,
			m_bOpenedOnce ? OPEN_ALWAYS : CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
		m_bOpenedOnce = true;
		if(m_hFile == INVALID_HANDLE_VALUE)
			HHLogError("cannot open log file %s (error %u)", HHNarrow(m_wstrPath).c_str(), (unsigned)GetLastError());
	}
	LeaveCriticalSection(&m_cs);
}

void HHLogFile::FlushLocked(void)
{
	if(m_hFile != INVALID_HANDLE_VALUE && !m_strBuffer.empty())
	{
		DWORD dwWritten = 0;
		WriteFile(m_hFile, m_strBuffer.data(), (DWORD)m_strBuffer.size(), &dwWritten, NULL);
	}
	m_strBuffer.clear();
}

void HHLogFile::Close(void)
{
	EnterCriticalSection(&m_cs);
	FlushLocked();
	if(m_hFile != INVALID_HANDLE_VALUE)
	{
		CloseHandle(m_hFile);
		m_hFile = INVALID_HANDLE_VALUE;
	}
	LeaveCriticalSection(&m_cs);
}

static void AppendText(std::string& out, const char* sz)
{
	for(; *sz; ++sz)
	{
		if(*sz == '\n')
			out += '\r';
		out += *sz;
	}
}

void HHLogFile::Write(const char* szPrefix, const TCHAR* format, va_list args)
{
	if(!HHLogFileMgr::Get().IsLoggingEnabled() || !format)
		return;
	std::string strText = HHFormatV(format, args);
	EnterCriticalSection(&m_cs);
	if(m_hFile != INVALID_HANDLE_VALUE)
	{
		if(!(m_uiFlags & kDontTimeStamp))
			m_strBuffer += HHFormat("[%.3f] ", HHSeconds());
		AppendText(m_strBuffer, szPrefix);
		AppendText(m_strBuffer, strText.c_str());
		if(strText.empty() || strText[strText.size() - 1] != '\n')
			m_strBuffer += "\r\n";
		if(!(m_uiFlags & kDontFlushOnWrite) || m_strBuffer.size() >= 65536)
			FlushLocked();
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
// The full path: the DLL finds the Logs folder from it (GetFullPathNameW on the returned name).
LPCWSTR HHLogFile::GetFileName() const { return m_wstrPath.c_str(); }
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
