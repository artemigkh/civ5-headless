-- Which game-core Lua tables exist in a front-end context (seed pinning via Lua needs Game there).
return {Game = type(Game), PreGame = type(PreGame), Map = type(Map), Players = type(Players),
	pending = (Game and Game.GetHeadlessPendingSeeds) and {Game.GetHeadlessPendingSeeds()} or "n/a"}
