// Phase A database (H8) and localization (H9): per-run copies of the game-built databases.
#pragma once
#include "HHCommon.h"

class HHDatabases
{
public:
	HHDatabases();
	~HHDatabases();

	// Copies the game and localization databases into <run>\db\ and opens the copies.
	bool OpenGameDatabase(const std::string& strSource);
	bool InitLocalization(const std::string& strLocSource, const std::string& strIcuData, const std::string& strLanguage);
	void ShutdownLocalization();
	void Close();

	Database::Connection* GetGame() { return m_pGame; }
	Database::Connection* GetLocalization() { return m_pLoc; }
	const std::string& GetGameCopyPath() const { return m_strGameCopy; }
	const std::string& GetLocCopyPath() const { return m_strLocCopy; }

	// SELECT COUNT(*) on the open game database; -1 on error.
	int CountRows(const char* szTable);

private:
	bool CopyIntoRun(const std::string& strSource, std::string& strCopy);
	Database::Connection* m_pGame;
	Database::Connection* m_pLoc;
	std::string m_strGameCopy;
	std::string m_strLocCopy;
	bool m_bLocalization;
};
