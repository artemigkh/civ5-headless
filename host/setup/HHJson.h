// Minimal JSON for the host: a parser for resolved game specs and a writer that turns Lua
// values into JSON with a deterministic layout (object keys sorted, integers without a
// fraction), so two runs of the same game give byte-identical files.
#pragma once
#include "HHCommon.h"

class HHJson
{
public:
	enum Type { JNULL, JBOOL, JNUMBER, JSTRING, JARRAY, JOBJECT };

	HHJson() : m_eType(JNULL), m_b(false), m_d(0.0) {}

	static bool Parse(const std::string& strText, HHJson& kOut, std::string& strError);
	static bool ParseFile(const std::string& strPath, HHJson& kOut, std::string& strError);

	Type GetType() const { return m_eType; }
	bool IsNull() const { return m_eType == JNULL; }
	bool IsObject() const { return m_eType == JOBJECT; }
	bool IsArray() const { return m_eType == JARRAY; }

	// Member access; a missing key gives a null value.
	const HHJson& operator[](const char* szKey) const;
	const HHJson& At(size_t i) const { return m_array[i]; }
	size_t Size() const { return m_eType == JARRAY ? m_array.size() : m_object.size(); }
	const std::vector<std::pair<std::string, HHJson> >& Members() const { return m_object; }
	bool Has(const char* szKey) const;

	int AsInt(int iDefault = 0) const;
	double AsDouble(double dDefault = 0.0) const;
	bool AsBool(bool bDefault = false) const;
	std::string AsString(const std::string& strDefault = std::string()) const;

private:
	friend class HHJsonParser;
	Type m_eType;
	bool m_b;
	double m_d;
	std::string m_s;
	std::vector<HHJson> m_array;
	std::vector<std::pair<std::string, HHJson> > m_object;
};

std::string HHJsonEscape(const std::string& s);
std::string HHJsonNumber(double d);

// Serialises the Lua value at index idx (tables: arrays when keys are exactly 1..n,
// otherwise objects with sorted string keys). Functions/userdata become their type name.
std::string HHLuaToJson(lua_State* L, int idx, int iIndent = 1);

bool HHWriteTextFile(const std::string& strPath, const std::string& strText);
