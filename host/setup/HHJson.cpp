#include "setup/HHJson.h"
#include "engine/HHRuntime.h"

class HHJsonParser
{
public:
	HHJsonParser(const std::string& s) : m_s(s), m_i(0) {}

	bool ParseDocument(HHJson& out, std::string& err)
	{
		if(!ParseValue(out, err))
			return false;
		SkipSpace();
		if(m_i != m_s.size())
		{
			err = HHFormat("trailing characters at offset %u", (unsigned)m_i);
			return false;
		}
		return true;
	}

private:
	void SkipSpace()
	{
		while(m_i < m_s.size() && (m_s[m_i] == ' ' || m_s[m_i] == '\t' || m_s[m_i] == '\r' || m_s[m_i] == '\n'))
			++m_i;
	}

	bool Fail(std::string& err, const char* szWhat)
	{
		err = HHFormat("%s at offset %u", szWhat, (unsigned)m_i);
		return false;
	}

	bool ParseString(std::string& out, std::string& err)
	{
		if(m_s[m_i] != '"')
			return Fail(err, "expected string");
		++m_i;
		out.clear();
		while(m_i < m_s.size() && m_s[m_i] != '"')
		{
			char c = m_s[m_i++];
			if(c != '\\')
			{
				out += c;
				continue;
			}
			if(m_i >= m_s.size())
				return Fail(err, "bad escape");
			char e = m_s[m_i++];
			switch(e)
			{
			case '"': out += '"'; break;
			case '\\': out += '\\'; break;
			case '/': out += '/'; break;
			case 'b': out += '\b'; break;
			case 'f': out += '\f'; break;
			case 'n': out += '\n'; break;
			case 'r': out += '\r'; break;
			case 't': out += '\t'; break;
			case 'u':
			{
				if(m_i + 4 > m_s.size())
					return Fail(err, "bad \\u escape");
				unsigned cp = strtoul(m_s.substr(m_i, 4).c_str(), NULL, 16);
				m_i += 4;
				// Surrogate pair
				if(cp >= 0xD800 && cp < 0xDC00 && m_i + 6 <= m_s.size() && m_s[m_i] == '\\' && m_s[m_i + 1] == 'u')
				{
					unsigned lo = strtoul(m_s.substr(m_i + 2, 4).c_str(), NULL, 16);
					m_i += 6;
					cp = 0x10000 + ((cp - 0xD800) << 10) + (lo - 0xDC00);
				}
				if(cp < 0x80) out += (char)cp;
				else if(cp < 0x800) { out += (char)(0xC0 | (cp >> 6)); out += (char)(0x80 | (cp & 0x3F)); }
				else if(cp < 0x10000) { out += (char)(0xE0 | (cp >> 12)); out += (char)(0x80 | ((cp >> 6) & 0x3F)); out += (char)(0x80 | (cp & 0x3F)); }
				else { out += (char)(0xF0 | (cp >> 18)); out += (char)(0x80 | ((cp >> 12) & 0x3F)); out += (char)(0x80 | ((cp >> 6) & 0x3F)); out += (char)(0x80 | (cp & 0x3F)); }
				break;
			}
			default:
				return Fail(err, "bad escape");
			}
		}
		if(m_i >= m_s.size())
			return Fail(err, "unterminated string");
		++m_i;
		return true;
	}

	bool ParseValue(HHJson& out, std::string& err)
	{
		SkipSpace();
		if(m_i >= m_s.size())
			return Fail(err, "unexpected end");
		const char c = m_s[m_i];
		if(c == '{')
		{
			out.m_eType = HHJson::JOBJECT;
			++m_i;
			SkipSpace();
			if(m_i < m_s.size() && m_s[m_i] == '}') { ++m_i; return true; }
			for(;;)
			{
				SkipSpace();
				std::string key;
				if(!ParseString(key, err))
					return false;
				SkipSpace();
				if(m_i >= m_s.size() || m_s[m_i] != ':')
					return Fail(err, "expected ':'");
				++m_i;
				out.m_object.push_back(std::make_pair(key, HHJson()));
				if(!ParseValue(out.m_object.back().second, err))
					return false;
				SkipSpace();
				if(m_i < m_s.size() && m_s[m_i] == ',') { ++m_i; continue; }
				if(m_i < m_s.size() && m_s[m_i] == '}') { ++m_i; return true; }
				return Fail(err, "expected ',' or '}'");
			}
		}
		if(c == '[')
		{
			out.m_eType = HHJson::JARRAY;
			++m_i;
			SkipSpace();
			if(m_i < m_s.size() && m_s[m_i] == ']') { ++m_i; return true; }
			for(;;)
			{
				out.m_array.push_back(HHJson());
				if(!ParseValue(out.m_array.back(), err))
					return false;
				SkipSpace();
				if(m_i < m_s.size() && m_s[m_i] == ',') { ++m_i; continue; }
				if(m_i < m_s.size() && m_s[m_i] == ']') { ++m_i; return true; }
				return Fail(err, "expected ',' or ']'");
			}
		}
		if(c == '"')
		{
			out.m_eType = HHJson::JSTRING;
			return ParseString(out.m_s, err);
		}
		if(m_s.compare(m_i, 4, "true") == 0) { out.m_eType = HHJson::JBOOL; out.m_b = true; m_i += 4; return true; }
		if(m_s.compare(m_i, 5, "false") == 0) { out.m_eType = HHJson::JBOOL; out.m_b = false; m_i += 5; return true; }
		if(m_s.compare(m_i, 4, "null") == 0) { out.m_eType = HHJson::JNULL; m_i += 4; return true; }
		const char* start = m_s.c_str() + m_i;
		char* end = NULL;
		const double d = strtod(start, &end);
		if(end == start)
			return Fail(err, "unexpected character");
		out.m_eType = HHJson::JNUMBER;
		out.m_d = d;
		m_i += end - start;
		return true;
	}

	const std::string& m_s;
	size_t m_i;
};

bool HHJson::Parse(const std::string& strText, HHJson& kOut, std::string& strError)
{
	size_t start = 0;
	if(strText.size() >= 3 && (unsigned char)strText[0] == 0xEF && (unsigned char)strText[1] == 0xBB && (unsigned char)strText[2] == 0xBF)
		start = 3;
	const std::string text = strText.substr(start);
	HHJsonParser p(text);
	kOut = HHJson();
	return p.ParseDocument(kOut, strError);
}

bool HHJson::ParseFile(const std::string& strPath, HHJson& kOut, std::string& strError)
{
	FILE* f = _wfopen(HHWiden(strPath).c_str(), L"rb");
	if(!f)
	{
		strError = "cannot open " + strPath;
		return false;
	}
	std::string text;
	char buf[65536];
	size_t n;
	while((n = fread(buf, 1, sizeof(buf), f)) > 0)
		text.append(buf, n);
	fclose(f);
	return Parse(text, kOut, strError);
}

const HHJson& HHJson::operator[](const char* szKey) const
{
	static const HHJson s_null;
	if(m_eType != JOBJECT)
		return s_null;
	for(size_t i = 0; i < m_object.size(); ++i)
		if(m_object[i].first == szKey)
			return m_object[i].second;
	return s_null;
}

bool HHJson::Has(const char* szKey) const
{
	if(m_eType != JOBJECT)
		return false;
	for(size_t i = 0; i < m_object.size(); ++i)
		if(m_object[i].first == szKey)
			return true;
	return false;
}

int HHJson::AsInt(int iDefault) const
{
	if(m_eType == JNUMBER) return (int)m_d;
	if(m_eType == JBOOL) return m_b ? 1 : 0;
	if(m_eType == JSTRING) return atoi(m_s.c_str());
	return iDefault;
}

double HHJson::AsDouble(double dDefault) const
{
	if(m_eType == JNUMBER) return m_d;
	if(m_eType == JBOOL) return m_b ? 1.0 : 0.0;
	return dDefault;
}

bool HHJson::AsBool(bool bDefault) const
{
	if(m_eType == JBOOL) return m_b;
	if(m_eType == JNUMBER) return m_d != 0.0;
	return bDefault;
}

std::string HHJson::AsString(const std::string& strDefault) const
{
	if(m_eType == JSTRING) return m_s;
	if(m_eType == JNUMBER) return HHJsonNumber(m_d);
	return strDefault;
}

std::string HHJsonEscape(const std::string& s)
{
	std::string out;
	out.reserve(s.size() + 2);
	for(size_t i = 0; i < s.size(); ++i)
	{
		const unsigned char c = (unsigned char)s[i];
		switch(c)
		{
		case '"': out += "\\\""; break;
		case '\\': out += "\\\\"; break;
		case '\n': out += "\\n"; break;
		case '\r': out += "\\r"; break;
		case '\t': out += "\\t"; break;
		default:
			if(c < 0x20)
				out += HHFormat("\\u%04x", c);
			else
				out += (char)c;
		}
	}
	return out;
}

std::string HHJsonNumber(double d)
{
	if(d != d)
		return "null";
	if(d >= -2147483648.0 && d <= 2147483647.0 && (double)(int)d == d)
		return HHFormat("%d", (int)d);
	if(d >= -9.0e15 && d <= 9.0e15 && (double)(__int64)d == d)
		return HHFormat("%I64d", (__int64)d);
	return HHFormat("%.17g", d);
}

namespace
{
	void Indent(std::string& out, int iIndent, int iDepth)
	{
		if(iIndent <= 0)
			return;
		out += '\n';
		out.append((size_t)(iIndent * iDepth), ' ');
	}

	void LuaToJson(lua_State* L, int idx, int iIndent, int iDepth, std::string& out)
	{
		if(idx < 0 && idx > LUA_REGISTRYINDEX)
			idx = lua_gettop(L) + idx + 1;
		switch(lua_type(L, idx))
		{
		case LUA_TNIL: out += "null"; return;
		case LUA_TBOOLEAN: out += lua_toboolean(L, idx) ? "true" : "false"; return;
		case LUA_TNUMBER: out += HHJsonNumber(lua_tonumber(L, idx)); return;
		case LUA_TSTRING:
		{
			size_t len = 0;
			const char* s = lua_tolstring(L, idx, &len);
			out += '"';
			out += HHJsonEscape(std::string(s, len));
			out += '"';
			return;
		}
		case LUA_TTABLE:
			break;
		default:
			out += '"';
			out += lua_typename(L, lua_type(L, idx));
			out += '"';
			return;
		}
		if(iDepth > 64)
		{
			out += "\"(too deep)\"";
			return;
		}
		// Array if the keys are exactly 1..n.
		const size_t n = lua_objlen(L, idx);
		size_t count = 0;
		bool bArray = true;
		std::vector<std::pair<std::string, int> > keys; // string key, or index for numbers
		lua_pushnil(L);
		while(lua_next(L, idx) != 0)
		{
			++count;
			if(lua_type(L, -2) == LUA_TNUMBER)
			{
				const lua_Number k = lua_tonumber(L, -2);
				if(k < 1 || k > (lua_Number)n || (lua_Number)(int)k != k)
					bArray = false;
				lua_pushvalue(L, -2);
				keys.push_back(std::make_pair(std::string(lua_tostring(L, -1)), 1));
				lua_pop(L, 1);
			}
			else if(lua_type(L, -2) == LUA_TSTRING)
			{
				bArray = false;
				keys.push_back(std::make_pair(std::string(lua_tostring(L, -2)), 0));
			}
			else
				bArray = false;
			lua_pop(L, 1);
		}
		if(count != n)
			bArray = false;
		if(count == 0)
		{
			out += "{}";
			return;
		}
		if(bArray)
		{
			out += '[';
			for(size_t i = 1; i <= n; ++i)
			{
				if(i > 1)
					out += ',';
				Indent(out, iIndent, iDepth + 1);
				lua_rawgeti(L, idx, (int)i);
				LuaToJson(L, -1, iIndent, iDepth + 1, out);
				lua_pop(L, 1);
			}
			Indent(out, iIndent, iDepth);
			out += ']';
			return;
		}
		std::sort(keys.begin(), keys.end());
		out += '{';
		for(size_t i = 0; i < keys.size(); ++i)
		{
			if(i > 0)
				out += ',';
			Indent(out, iIndent, iDepth + 1);
			out += '"';
			out += HHJsonEscape(keys[i].first);
			out += "\":";
			if(iIndent > 0)
				out += ' ';
			if(keys[i].second)
				lua_pushnumber(L, strtod(keys[i].first.c_str(), NULL));
			else
				lua_pushstring(L, keys[i].first.c_str());
			lua_rawget(L, idx);
			LuaToJson(L, -1, iIndent, iDepth + 1, out);
			lua_pop(L, 1);
		}
		Indent(out, iIndent, iDepth);
		out += '}';
	}
}

std::string HHLuaToJson(lua_State* L, int idx, int iIndent)
{
	std::string out;
	LuaToJson(L, idx, iIndent, 0, out);
	return out;
}

bool HHWriteTextFile(const std::string& strPath, const std::string& strText)
{
	FILE* f = _wfopen(HHWiden(strPath).c_str(), L"wb");
	if(!f)
	{
		HHLogError("cannot write %s", strPath.c_str());
		return false;
	}
	fwrite(strText.data(), 1, strText.size(), f);
	fclose(f);
	return true;
}
