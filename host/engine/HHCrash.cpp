// Crash diagnostics: an access violation (or another fatal exception) inside a game DLL ends the host without a
// message. The handlers log the exception, the faulting module and offset, the registers and the return addresses
// found on the stack (module+offset; disassemble with dumpbin /disasm), so a DLL the host does not support yet shows
// where it stopped. First-chance faults are logged too (at most a few): a DLL may handle some itself.
#include "HHCommon.h"
#include "engine/HHRuntime.h"

namespace
{
	volatile LONG s_iFirstChance = 0;
	const LONG kMaxFirstChance = 4;

	std::string Where(DWORD dwAddress)
	{
		HMODULE hModule = NULL;
		if(!GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
		                       (LPCWSTR)(DWORD_PTR)dwAddress, &hModule) || !hModule)
			return HHFormat("0x%08lX", dwAddress);
		wchar_t sz[MAX_PATH];
		const DWORD n = GetModuleFileNameW(hModule, sz, MAX_PATH);
		std::string name = n ? HHNarrow(std::wstring(sz, n)) : std::string("?");
		const size_t slash = name.find_last_of("\\/");
		if(slash != std::string::npos)
			name = name.substr(slash + 1);
		return HHFormat("%s+0x%lX", name.c_str(), dwAddress - (DWORD)(DWORD_PTR)hModule);
	}

	bool IsCode(DWORD dwAddress)
	{
		MEMORY_BASIC_INFORMATION mbi;
		if(dwAddress < 0x10000 || !VirtualQuery((LPCVOID)(DWORD_PTR)dwAddress, &mbi, sizeof(mbi)))
			return false;
		const DWORD exec = PAGE_EXECUTE | PAGE_EXECUTE_READ | PAGE_EXECUTE_READWRITE | PAGE_EXECUTE_WRITECOPY;
		return mbi.State == MEM_COMMIT && mbi.Type == MEM_IMAGE && (mbi.Protect & exec) != 0;
	}

	void Report(const char* szKind, EXCEPTION_POINTERS* pInfo)
	{
		const EXCEPTION_RECORD* r = pInfo->ExceptionRecord;
		const CONTEXT* c = pInfo->ContextRecord;
		std::string detail;
		if(r->ExceptionCode == EXCEPTION_ACCESS_VIOLATION && r->NumberParameters >= 2)
			detail = HHFormat(" (%s 0x%08lX)", r->ExceptionInformation[0] == 0 ? "read" : r->ExceptionInformation[0] == 1 ? "write" : "execute",
			                  (DWORD)r->ExceptionInformation[1]);
		HHLogError("HHCRASH %s exception 0x%08lX%s at %s, phase %s", szKind, r->ExceptionCode, detail.c_str(),
		           Where((DWORD)(DWORD_PTR)r->ExceptionAddress).c_str(), HHGetPhase());
		HHLogError("HHCRASH registers eax=%08lX ebx=%08lX ecx=%08lX edx=%08lX esi=%08lX edi=%08lX ebp=%08lX esp=%08lX",
		           c->Eax, c->Ebx, c->Ecx, c->Edx, c->Esi, c->Edi, c->Ebp, c->Esp);
		// Return-address candidates: stack values that point into executable image pages.
		const NT_TIB* pTib = (const NT_TIB*)NtCurrentTeb();
		const DWORD* p = (const DWORD*)(DWORD_PTR)c->Esp;
		const DWORD* pEnd = (const DWORD*)pTib->StackBase;
		std::string stack;
		int n = 0;
		for(int i = 0; p < pEnd && i < 16384 && n < 24; ++p, ++i)
		{
			if(IsCode(*p))
			{
				stack += (n ? " " : "") + Where(*p);
				++n;
			}
		}
		HHLogError("HHCRASH stack %s", stack.c_str());
	}

	bool IsFatal(DWORD dwCode)
	{
		return dwCode == EXCEPTION_ACCESS_VIOLATION || dwCode == EXCEPTION_INT_DIVIDE_BY_ZERO ||
		       dwCode == EXCEPTION_STACK_OVERFLOW || dwCode == EXCEPTION_ILLEGAL_INSTRUCTION ||
		       dwCode == EXCEPTION_ARRAY_BOUNDS_EXCEEDED || dwCode == EXCEPTION_PRIV_INSTRUCTION;
	}

	LONG CALLBACK FirstChance(EXCEPTION_POINTERS* pInfo)
	{
		if(IsFatal(pInfo->ExceptionRecord->ExceptionCode) && InterlockedIncrement(&s_iFirstChance) <= kMaxFirstChance)
			Report("first-chance", pInfo);
		return EXCEPTION_CONTINUE_SEARCH;
	}

	LONG WINAPI Unhandled(EXCEPTION_POINTERS* pInfo)
	{
		Report("unhandled", pInfo);
		return EXCEPTION_EXECUTE_HANDLER;
	}
}

void HHInstallCrashHandler()
{
	AddVectoredExceptionHandler(1, FirstChance);
	SetUnhandledExceptionFilter(Unhandled);
}
