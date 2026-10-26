// FILogFileMgr / FILogFile for the DLL (GetLogFileMgr / PeekLogFileMgr exports).
// Every log goes to the run's Logs folder; a name with folders creates them below Logs. With keep patterns
// (--keep-log), a log whose name matches none is discarded: the DLL gets a log object and calls it as usual, and
// nothing is written (no file is created).
#pragma once
#include "HHCommon.h"

class HHLogFile : public FILogFile
{
public:
	HHLogFile(const std::wstring& wstrPath, const std::wstring& wstrName, uint uiFlags, bool bDiscard = false);
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
	bool m_bDiscard;                // never opened, writes dropped (--keep-log)
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
	void SetKeepPatterns(const std::vector<std::string>& patterns);  // empty: write every log
	size_t GetLogCount();
	size_t GetDiscardedCount();
	void CloseAll();

	static HHLogFileMgr& Get();

private:
	bool Keep(const std::wstring& strName) const;

	typedef std::map<std::wstring, HHLogFile*> LogMap;
	LogMap m_logs;
	std::wstring m_wstrFolder;
	std::vector<std::wstring> m_keep;  // lower-case wildcard patterns
	size_t m_nDiscarded;
	bool m_bEnabled;
	CRITICAL_SECTION m_cs;
};
