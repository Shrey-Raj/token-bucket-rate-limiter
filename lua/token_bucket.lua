local key = KEYS[1]
local max_capacity = tonumber(ARGV[1])
local refill_rate = tonumber(ARGV[2])
local requested = tonumber(ARGV[3])

local t = redis.call("TIME")
local now = tonumber(t[1]) + tonumber(t[2]) / 1000000

local data = redis.call("HMGET", key, "tokens", "last_updated")
local tokens = tonumber(data[1])
local last_updated = tonumber(data[2])

if not tokens or not last_updated then
    tokens = max_capacity
    last_updated = now
end

local elapsed = math.max(0, now - last_updated)
local tokens_to_add = elapsed * refill_rate
tokens = math.min(max_capacity, tokens + tokens_to_add)
last_updated = now

local allowed = 0
local retry_after = 0

if tokens >= requested then
    allowed = 1
    tokens = tokens - requested
else
    local needed = requested - tokens
    retry_after = math.ceil(needed / refill_rate)
end

redis.call("HSET", key, "tokens", tokens, "last_updated", last_updated)
redis.call("EXPIRE", key, 3600)

local reset_in_seconds = math.ceil((max_capacity - tokens) / refill_rate)

return {allowed, math.floor(tokens), retry_after, reset_in_seconds}