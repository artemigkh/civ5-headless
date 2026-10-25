// FILogFileMgr / FILogFile for the DLL (GetLogFileMgr / PeekLogFileMgr exports).
// Every log goes to the run's Logs folder; a name with folders creates them below Logs.
#pragma once
#include "HHCommon.h"

class HHLogFile : public FILogFile
{
public:
	HHLogFile(const std::wstring& wstrPath, const std::wstring& wstrName, uint uiFlags);
	virtual ~HHLogFile();

	virtual void Msg(const TCHAR* format, ...);
	virtual void DebugMsg(const TCHAR* format, ...);
	virtual void WarningMsg(const TCHAR* format, ...);
	virtual void ErrorMsg(const TCHAR* format, ...);
	virtual void SetFlags(uint uiFlags);
	virtual uint GetFlags() const;
	virtual void SetBufSize(int iSize);
	virtual LPCWSTR GetFileName() const;
	virtual void Close(void);
	virtual void Open(void);
	virtual void Archive(LPCWSTR wszArchiveName);

	void Write(const char* szPrefix, const TCHAR* format, va_list args);
	void FlushLocked(void);

private:
	std::wstring m_wstrPath;
	std::wstring m_wstrName;
	uint m_uiFlags;
	HANDLE m_hFile;                 // Win32 handle: a run opens more logs than the CRT's 512 FILE streams
	std::string m_strBuffer;        // pending text (CRLF), written on flush
	bool m_bOpenedOnce;
	CRITICAL_SECTION m_cs;
};

class HHLogFileMgr : public FILogFileMgr
{
public:
	HHLogFileMgr();
	virtual ~HHLogFileMgr();

	virtual void EnableLogging(void);
	virtual void DisableLogging(void);
	virtual FILogFile* GetLog(LPCWSTR wszFileName, uint uiFlags, const TCHAR* szTitleString = NULL);
	virtual FILogFile* GetLog(LPCSTR szFileName, uint uiFlags, const TCHAR* szTitleString = NULL);
	virtual bool DeleteLog(FILogFile* pLog);
	virtual bool DeleteLog(LPCWSTR wszFileName);
	virtual bool IsLoggingEnabled(void);

	void SetFolder(const std::string& strLogsDir);
	size_t GetLogCount();
	void CloseAll();

	static HHLogFileMgr& Get();

private:
	typedef std::map<std::wstring, HHLogFile*> LogMap;
	LogMap m_logs;
	std::wstring m_wstrFolder;
	bool m_bEnabled;
	CRITICAL_SECTION m_cs;
};
