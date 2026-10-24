-- Dump the digest sections at the current turn (game core idle) for hhdigest.py verify and diffs.
local turn = Game.GetGameTurn()
local folder = string.gsub("{RUN}/dump-t" .. string.format("%03d", turn), "/", "\\")
local line, err = Game.DumpHeadlessState(folder)
local digest = Game.GetHeadlessDigest()
return {turn = turn, folder = folder, line = line, error = err, total = digest.total, sizes = digest.sizes}
