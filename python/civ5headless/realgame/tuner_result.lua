Civ5StackAutomationRun = function(source, marker)
 local function quote(s)
  return '"' .. s:gsub('[%z\1-\31\\"]', function(c)
   if c == '"' then return '\\"' end
   if c == '\\' then return '\\\\' end
   return string.format('\\u%04x', string.byte(c))
  end) .. '"'
 end
 local seen = {}
 local items = 0
 local function encode(v, depth)
  items = items + 1
  if items > 10000 or depth > 16 then error('Result exceeds serialization limits') end
  local t = type(v)
  if t == 'nil' then return 'null' end
  if t == 'boolean' then return tostring(v) end
  if t == 'number' then
   if v ~= v or v == math.huge or v == -math.huge then error('Non-finite number') end
   return tostring(v)
  end
  if t == 'string' then return quote(v) end
  if t ~= 'table' then error('Unsupported result type: ' .. t) end
  if seen[v] then error('Circular result table') end
  seen[v] = true
  local count, maximum, array = 0, 0, true
  for k in pairs(v) do
   count = count + 1
   if type(k) ~= 'number' or k < 1 or k ~= math.floor(k) then array = false
   else maximum = math.max(maximum, k) end
  end
  array = array and count > 0 and count == maximum
  local out = {}
  if array then
   for i = 1, count do out[i] = encode(v[i], depth + 1) end
  else
   for k, value in pairs(v) do
    if type(k) ~= 'string' then error('Object keys must be strings; use a dense array for numeric keys') end
    out[#out + 1] = quote(k) .. ':' .. encode(value, depth + 1)
   end
   table.sort(out)
  end
  seen[v] = nil
  return (array and '[' or '{') .. table.concat(out, ',') .. (array and ']' or '}')
 end
 local function run()
  local f, err = loadstring(source, 'Civ5Automation')
  if not f then return {ok = false, error = err} end
  local function collect(...) return {n = select('#', ...), ...} end
  local values = collect(pcall(f))
  if not values[1] then return {ok = false, error = tostring(values[2])} end
  local out = {}
  -- Encode return positions explicitly so nil values are retained.
  for i = 2, values.n do out[#out + 1] = encode(values[i], 0) end
  return {ok = true, returns_json = '[' .. table.concat(out, ',') .. ']'}
 end
 local ok, result = pcall(run)
 if not ok then result = {ok = false, error = tostring(result)} end
 local payload
 if result.ok then payload = '{"ok":true,"values":' .. result.returns_json .. '}'
 else payload = '{"ok":false,"error":' .. quote(result.error) .. '}' end
 if #payload > 262144 then payload = '{"ok":false,"error":"Result exceeds 256 KiB"}' end
 -- Short ASCII output avoids engine console limits and preserves UTF-8 bytes.
 local total = math.ceil(#payload / 256)
 for i = 1, total do
  local chunk = payload:sub((i - 1) * 256 + 1, i * 256)
  local hex = chunk:gsub('.', function(c) return string.format('%02x', string.byte(c)) end)
  print(marker .. i .. '/' .. total .. ':' .. hex)
 end
end
