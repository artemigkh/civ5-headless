// FIFileSystem implementation handed to the DLL through the GetFileSystemMgr export.
#pragma once
#include "HHCommon.h"
#include <FireWorks/FIFile.h>

class HHFileSystem : public FIFileSystem
{
public:
	virtual FIFile* Create(const char* szFileName = NULL, FIFile::OpenMode eOpenMode = FIFile::modeRead, dword dwFlags = FFILE_FLAG_DEFAULT, uint uiBufferSize = FFILE_DEFAULT_BUFFER_SIZE);
	virtual FIFile* Create(const wchar* wszFileName, FIFile::OpenMode eOpenMode = FIFile::modeRead, dword dwFlags = FFILE_FLAG_DEFAULT, uint uiBufferSize = FFILE_DEFAULT_BUFFER_SIZE);
	virtual FileErr Delete(const char* szFileName);
	virtual FileErr Delete(const wchar* wszFileName);
	virtual FileErr ReadAll(const char* szFileName, byte** pucBufferOut, size_t* puiBufferSizeOut, dword dwFlags = FFILE_FLAG_DEFAULT);
	virtual FileErr ReadAll(const wchar* wszFileName, byte** pucBufferOut, size_t* puiBufferSizeOut, dword dwFlags = FFILE_FLAG_DEFAULT);
	virtual FileErr ReadAll(const char* szFileName, byte** pucBufferOut, size_t* puiBufferSizeOut, dword dwFlags, FIFile::Allocator& alloc);
	virtual FileErr ReadAll(const wchar* wszFileName, byte** pucBufferOut, size_t* puiBufferSizeOut, dword dwFlags, FIFile::Allocator& alloc);
	virtual bool Exist(const char* pszFileName);
	virtual bool Exist(const wchar* pwszFileName);
	virtual uint GetLength(const char* szFileName);
	virtual uint GetLength(const wchar* wszFileName);
	virtual FFileTimestamp GetLastWriteTime(const char* pFileName);
	virtual bool IsFileCatalogEnabled();
	virtual FFileErrorHandler* GetErrorHandler();

	static HHFileSystem& Get();
};
