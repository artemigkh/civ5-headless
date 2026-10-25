#include "setup/HHDatabase.h"
#include "engine/HHRuntime.h"
#include "engine/HHLogFiles.h"

namespace
{
	// Database and localization messages go to the run's Logs, as the engine's Database.log.
	class HHDatabaseLogger : public Database::IDatabaseLogger
	{
	public:
		virtual void Log(const char* szMessage, LogTypes eType)
		{
			FILogFile* pLog = HHLogFileMgr::Get().GetLog("Database.log", 0);
			const char* szPrefix = eType == TYPE_ERROR ? "ERROR: " : (eType == TYPE_WARNING ? "WARNING: " : "");
			pLog->Msg("%s%s", szPrefix, szMessage ? szMessage : "");
			if(eType == TYPE_ERROR)
				HHLog("Database error: %s", szMessage ? szMessage : "");
		}
	};

	class HHLocalizationLogger : public Localization::ILocalizationLogger
	{
	public:
		virtual void Log(const char* szMessage, LogTypes eType)
		{
			FILogFile* pLog = HHLogFileMgr::Get().GetLog("Localization.log", 0);
			const char* szPrefix = eType == TYPE_ERROR ? "ERROR: " : (eType == TYPE_WARNING ? "WARNING: " : "");
			pLog->Msg("%s%s", szPrefix, szMessage ? szMessage : "");
		}
	};

	// Database::Connection owns its logger (it deletes it when the connection is destroyed), so every
	// connection gets its own heap logger. A shared static one was deleted at HHDatabases::Close: heap
	// corruption at shutdown that crashed or hung some builds after "game DLL unloaded".
	// Localization::SetLogger's ownership is unknown: a heap object as well, never deleted by the host.
}

HHDatabases::HHDatabases() : m_pGame(NULL), m_pLoc(NULL), m_bLocalization(false) {}

HHDatabases::~HHDatabases()
{
	ShutdownLocalization();
	Close();
}

bool HHDatabases::CopyIntoRun(const std::string& strSource, std::string& strCopy)
{
	const std::string& dbDir = HHGetPaths().db;
	size_t slash = strSource.find_last_of("\\/");
	std::string name = slash == std::string::npos ? strSource : strSource.substr(slash + 1);
	strCopy = dbDir + name;
	// Never open the source: it can be the live cache of a running game.
	if(!CopyFileW(HHWiden(strSource).c_str(), HHWiden(strCopy).c_str(), FALSE))
	{
		HHLogError("cannot copy %s to %s (error %lu)", strSource.c_str(), strCopy.c_str(), GetLastError());
		return false;
	}
	// A copy taken while SQLite holds a journal is still consistent for reading only if the
	// journal is absent; report it so a bad copy is recognisable.
	if(HHFileExists(strSource + "-journal") || HHFileExists(strSource + "-wal"))
		HHLog("warning: %s has a journal/WAL next to it; the copy may be mid-transaction", strSource.c_str());
	HHLog("copied %s -> %s", strSource.c_str(), strCopy.c_str());
	return true;
}

bool HHDatabases::OpenGameDatabase(const std::string& strSource)
{
	if(!CopyIntoRun(strSource, m_strGameCopy))
		return false;
	m_pGame = new Database::Connection();
	m_pGame->SetLogger(new HHDatabaseLogger());
	// The DLL writes to the game database (post-processing, ANALYZE): read-write on the copy.
	// Host strings are UTF-8, as SQLite expects for file names.
	if(!m_pGame->Open(m_strGameCopy.c_str(), Database::OPEN_READWRITE))
	{
		HHLogError("cannot open game database %s: %s", m_strGameCopy.c_str(), m_pGame->ErrorMessage());
		delete m_pGame;
		m_pGame = NULL;
		return false;
	}
	return true;
}

bool HHDatabases::InitLocalization(const std::string& strLocSource, const std::string& strIcuData, const std::string& strLanguage)
{
	if(!CopyIntoRun(strLocSource, m_strLocCopy))
		return false;
	m_pLoc = new Database::Connection();
	m_pLoc->SetLogger(new HHDatabaseLogger());
	if(!m_pLoc->Open(m_strLocCopy.c_str(), Database::OPEN_READWRITE))
	{
		HHLogError("cannot open localization database %s: %s", m_strLocCopy.c_str(), m_pLoc->ErrorMessage());
		delete m_pLoc;
		m_pLoc = NULL;
		return false;
	}
	Localization::SetLogger(new HHLocalizationLogger());
	const std::wstring icu = HHWiden(strIcuData);
	if(!Localization::Initialize(icu.c_str(), *m_pLoc, "Languages", strLanguage.c_str(), false))
	{
		HHLogError("Localization::Initialize failed (ICU %s, language %s)", strIcuData.c_str(), strLanguage.c_str());
		return false;
	}
	m_bLocalization = true;
	return true;
}

void HHDatabases::ShutdownLocalization()
{
	if(m_bLocalization)
	{
		Localization::Shutdown();
		m_bLocalization = false;
	}
}

void HHDatabases::Close()
{
	if(m_pLoc)
	{
		m_pLoc->Close();
		delete m_pLoc;
		m_pLoc = NULL;
	}
	if(m_pGame)
	{
		m_pGame->Close();
		delete m_pGame;
		m_pGame = NULL;
	}
}

int HHDatabases::CountRows(const char* szTable)
{
	if(!m_pGame)
		return -1;
	Database::Results kResults;
	std::string sql = HHFormat("SELECT COUNT(*) FROM \"%s\"", szTable);
	if(!m_pGame->Execute(kResults, sql.c_str()) || !kResults.Step())
		return -1;
	return kResults.GetInt(0);
}

int HHDatabases::IdRange(const char* szTable)
{
	if(!m_pGame)
		return -1;
	Database::Results kResults;
	std::string sql = HHFormat("SELECT MAX(ID) + 1 FROM \"%s\"", szTable);
	if(!m_pGame->Execute(kResults, sql.c_str()) || !kResults.Step())
		return -1;
	return kResults.GetInt(0);
}
