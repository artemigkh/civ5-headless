// FIFileSystem / FIFile for the DLL (GetFileSystemMgr export): plain Win32 files.
// The DLL uses it to write Civ5SavedGameDatabase.db (CvGame::readSaveGameDB) and to test
// map scripts for existence (CvPreGame). Relative names resolve against the working
// directory, which the driver sets to the run folder.
#include "engine/HHFileSystem.h"
#include "engine/HHRuntime.h"

namespace
{
	class HHFile : public FIFile
	{
	public:
		HHFile() : m_hFile(INVALID_HANDLE_VALUE) {}
		virtual ~HHFile() { Close(); }

		virtual FileErr Open(const char* szFileName, OpenMode eOpenMode, dword dwFlags, uint uiBufferSize)
		{
			if(!szFileName)
				return FILE_BADNAME;
			return Open(HHWiden(szFileName, CP_ACP).c_str(), eOpenMode, dwFlags, uiBufferSize);
		}
		virtual FileErr Open(const wchar* wszFileName, OpenMode eOpenMode, dword dwFlags, uint)
		{
			Close();
			if(!wszFileName)
				return FILE_BADNAME;
			DWORD access = 0, creation = OPEN_EXISTING, share = FILE_SHARE_READ;
			switch(eOpenMode)
			{
			case modeRead: access = GENERIC_READ; creation = OPEN_EXISTING; break;
			case modeWrite: access = GENERIC_WRITE; creation = CREATE_ALWAYS; break;
			case modeEdit: access = GENERIC_READ | GENERIC_WRITE; creation = OPEN_ALWAYS; break;
			default: return FILE_BADMODE;
			}
			DWORD attrs = FILE_ATTRIBUTE_NORMAL;
#ifdef FFILE_FLAG_RANDOM_ACCESS
			if(dwFlags & FFILE_FLAG_RANDOM_ACCESS)
				attrs |= FILE_FLAG_RANDOM_ACCESS;
#endif
			m_hFile = CreateFileW(wszFileName, access, share, NULL, creation, attrs, NULL);
			if(m_hFile == INVALID_HANDLE_VALUE)
				return FILE_NOTFOUND;
			m_wstrName = wszFileName;
			return FILE_OK;
		}
		virtual FileErr Close(void)
		{
			if(m_hFile != INVALID_HANDLE_VALUE)
			{
				CloseHandle(m_hFile);
				m_hFile = INVALID_HANDLE_VALUE;
			}
			return FILE_OK;
		}
		virtual const wchar_t* GetFileName() { return m_wstrName.c_str(); }
		virtual byte* GetViewCaret(void) const { return NULL; }
		virtual byte* GetViewEnd(void) const { return NULL; }
		virtual byte* GetViewPtr(void) const { return NULL; }
		virtual uint GetLength(void) const
		{
			if(m_hFile == INVALID_HANDLE_VALUE)
				return 0;
			LARGE_INTEGER size;
			return GetFileSizeEx(m_hFile, &size) ? (uint)size.QuadPart : 0;
		}
		virtual void SetLength(uint size)
		{
			if(m_hFile == INVALID_HANDLE_VALUE)
				return;
			uint pos = GetPosition();
			LARGE_INTEGER li;
			li.QuadPart = size;
			SetFilePointerEx(m_hFile, li, NULL, FILE_BEGIN);
			SetEndOfFile(m_hFile);
			li.QuadPart = std::min(pos, size);
			SetFilePointerEx(m_hFile, li, NULL, FILE_BEGIN);
		}
		virtual bool IsOpen(void) const { return m_hFile != INVALID_HANDLE_VALUE; }
		virtual bool IsMapped(void) const { return false; }
		virtual uint Seek(long lOffset, SeekMode eOrigin)
		{
			if(m_hFile == INVALID_HANDLE_VALUE)
				return 0;
			LARGE_INTEGER li, out;
			li.QuadPart = lOffset;
			DWORD method = eOrigin == begin ? FILE_BEGIN : (eOrigin == current ? FILE_CURRENT : FILE_END);
			return SetFilePointerEx(m_hFile, li, &out, method) ? (uint)out.QuadPart : 0;
		}
		virtual uint SeekToBegin() { return Seek(0, begin); }
		virtual uint SeekToEnd() { return Seek(0, end); }
		virtual uint GetPosition() { return Seek(0, current); }
		virtual void Rewind(void) { Seek(0, begin); }
		virtual bool IsEOF(void) { return GetPosition() >= GetLength(); }
		virtual uint Read(void* pData, uint size)
		{
			DWORD n = 0;
			if(m_hFile == INVALID_HANDLE_VALUE || !ReadFile(m_hFile, pData, size, &n, NULL))
				return 0;
			return n;
		}
		virtual uint Write(const void* pData, uint size)
		{
			DWORD n = 0;
			if(m_hFile == INVALID_HANDLE_VALUE || !WriteFile(m_hFile, pData, size, &n, NULL))
				return 0;
			return n;
		}
		virtual uint Flush(void)
		{
			if(m_hFile != INVALID_HANDLE_VALUE)
				FlushFileBuffers(m_hFile);
			return 0;
		}

	private:
		HANDLE m_hFile;
		std::wstring m_wstrName;
	};

	FileErr ReadAllImpl(const wchar_t* wszFileName, byte** ppBuffer, size_t* pSize, FIFile::Allocator* pAlloc)
	{
		if(!ppBuffer)
			return FILE_BADNAME;
		*ppBuffer = NULL;
		if(pSize)
			*pSize = 0;
		HHFile file;
		FileErr err = file.Open(wszFileName, FIFile::modeRead, 0, 0);
		if(err != FILE_OK)
			return err;
		uint size = file.GetLength();
		// One extra zero byte, so text buffers are terminated.
		byte* pBuffer = pAlloc ? pAlloc->Allocate(size + 1) : new byte[size + 1];
		uint n = file.Read(pBuffer, size);
		pBuffer[n] = 0;
		*ppBuffer = pBuffer;
		if(pSize)
			*pSize = n;
		return FILE_OK;
	}
}

FIFile* HHFileSystem::Create(const char* szFileName, FIFile::OpenMode eOpenMode, dword dwFlags, uint uiBufferSize)
{
	HH_IMPL_CALL("FIFileSystem::Create");
	return Create(szFileName ? HHWiden(szFileName, CP_ACP).c_str() : NULL, eOpenMode, dwFlags, uiBufferSize);
}

FIFile* HHFileSystem::Create(const wchar* wszFileName, FIFile::OpenMode eOpenMode, dword dwFlags, uint uiBufferSize)
{
	HH_IMPL_CALL("FIFileSystem::Create");
	HHFile* pFile = new HHFile();
	if(wszFileName && pFile->Open(wszFileName, eOpenMode, dwFlags, uiBufferSize) != FILE_OK)
	{
		HHLog("FIFileSystem::Create: cannot open %s (mode %d)", HHNarrow(wszFileName).c_str(), (int)eOpenMode);
		delete pFile;
		return NULL;
	}
	return pFile;
}

FileErr HHFileSystem::Delete(const char* szFileName)
{
	return szFileName ? Delete(HHWiden(szFileName, CP_ACP).c_str()) : FILE_BADNAME;
}

FileErr HHFileSystem::Delete(const wchar* wszFileName)
{
	HH_IMPL_CALL("FIFileSystem::Delete");
	return (wszFileName && DeleteFileW(wszFileName)) ? FILE_OK : FILE_NOTFOUND;
}

FileErr HHFileSystem::ReadAll(const char* szFileName, byte** pucBufferOut, size_t* puiBufferSizeOut, dword)
{
	HH_IMPL_CALL("FIFileSystem::ReadAll");
	return szFileName ? ReadAllImpl(HHWiden(szFileName, CP_ACP).c_str(), pucBufferOut, puiBufferSizeOut, NULL) : FILE_BADNAME;
}

FileErr HHFileSystem::ReadAll(const wchar* wszFileName, byte** pucBufferOut, size_t* puiBufferSizeOut, dword)
{
	HH_IMPL_CALL("FIFileSystem::ReadAll");
	return ReadAllImpl(wszFileName, pucBufferOut, puiBufferSizeOut, NULL);
}

FileErr HHFileSystem::ReadAll(const char* szFileName, byte** pucBufferOut, size_t* puiBufferSizeOut, dword, FIFile::Allocator& alloc)
{
	HH_IMPL_CALL("FIFileSystem::ReadAll");
	return szFileName ? ReadAllImpl(HHWiden(szFileName, CP_ACP).c_str(), pucBufferOut, puiBufferSizeOut, &alloc) : FILE_BADNAME;
}

FileErr HHFileSystem::ReadAll(const wchar* wszFileName, byte** pucBufferOut, size_t* puiBufferSizeOut, dword, FIFile::Allocator& alloc)
{
	HH_IMPL_CALL("FIFileSystem::ReadAll");
	return ReadAllImpl(wszFileName, pucBufferOut, puiBufferSizeOut, &alloc);
}

bool HHFileSystem::Exist(const char* pszFileName)
{
	return pszFileName && Exist(HHWiden(pszFileName, CP_ACP).c_str());
}

bool HHFileSystem::Exist(const wchar* pwszFileName)
{
	HH_IMPL_CALL("FIFileSystem::Exist");
	if(!pwszFileName)
		return false;
	DWORD attr = GetFileAttributesW(pwszFileName);
	return attr != INVALID_FILE_ATTRIBUTES && !(attr & FILE_ATTRIBUTE_DIRECTORY);
}

uint HHFileSystem::GetLength(const char* szFileName)
{
	return szFileName ? GetLength(HHWiden(szFileName, CP_ACP).c_str()) : 0;
}

uint HHFileSystem::GetLength(const wchar* wszFileName)
{
	HH_IMPL_CALL("FIFileSystem::GetLength");
	WIN32_FILE_ATTRIBUTE_DATA data;
	if(!wszFileName || !GetFileAttributesExW(wszFileName, GetFileExInfoStandard, &data))
		return 0;
	return data.nFileSizeLow;
}

FFileTimestamp HHFileSystem::GetLastWriteTime(const char* pFileName)
{
	HH_IMPL_CALL("FIFileSystem::GetLastWriteTime");
	WIN32_FILE_ATTRIBUTE_DATA data;
	memset(&data, 0, sizeof(data));
	if(pFileName)
		GetFileAttributesExW(HHWiden(pFileName, CP_ACP).c_str(), GetFileExInfoStandard, &data);
	return FFileTimestamp(data.ftLastWriteTime);
}

bool HHFileSystem::IsFileCatalogEnabled()
{
	HH_IMPL_CALL("FIFileSystem::IsFileCatalogEnabled");
	return false;
}

FFileErrorHandler* HHFileSystem::GetErrorHandler()
{
	HH_IMPL_CALL("FIFileSystem::GetErrorHandler");
	return NULL;
}

HHFileSystem& HHFileSystem::Get()
{
	static HHFileSystem* s_pFileSystem = new HHFileSystem();
	return *s_pFileSystem;
}
