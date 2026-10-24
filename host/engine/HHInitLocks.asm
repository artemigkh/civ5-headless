; std::_Init_locks& std::_Init_locks::operator=(const std::_Init_locks&) for the exe's export
; table (the 22nd FireWorks-era export). C++ cannot define it (the class comes from the CRT
; headers) and the .def/EXPORT alias syntax cuts the name at its first '@', so the symbol
; is defined here under its decorated name and listed in civ5headless.def as is.
; __thiscall: this in ecx, one stack argument; returns this.
.386
.model flat
EXTERN _HHCountInitLocksAssign:PROC
.code
??4_Init_locks@std@@QAEAAV01@ABV01@@Z PROC PUBLIC
	push ecx
	call _HHCountInitLocksAssign
	pop ecx
	mov eax, ecx
	ret 4
??4_Init_locks@std@@QAEAAV01@ABV01@@Z ENDP
END
