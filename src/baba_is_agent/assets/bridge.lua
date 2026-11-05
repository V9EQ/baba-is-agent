-- Baba MCP telemetry v2: official mod hooks + native INI transport. No io/os.
local path = 'Data/Languages/baba_mcp/'
local last_request = ''
local frame, turns, wins = 0, 0, 0
local won = false
local failed = false
local action_error = nil
local pending = nil
local executed = 0
local function dispatch(request)
  if request.op == nil or request.op == 'state' then return end
  local playing = editor.strings[MENU] == 'ingame' and generaldata2.values[INPAUSEMENU] == 0 and generaldata.values[IGNORE] == 0
  if not playing then error('Not ready for gameplay; use menu input') end
  if request.op == 'move' then
    local allowed = {up=true,down=true,left=true,right=true,idle=true}
    if not allowed[request.key] then error('Invalid direction') end
    if generaldata5.values[AUTO_ON] ~= 0 then error('AUTO level requires realtime keyboard input') end
    command(request.key,1)
  elseif request.op == 'undo' then
    undo()
    code()
    MF_update()
  elseif request.op == 'restart' then
    MF_restart(true)
  else
    error('Unknown operation')
  end
end
local function encode(v)
  local t = type(v)
  if t == 'nil' then return 'null' end
  if t == 'boolean' or t == 'number' then return tostring(v) end
  if t == 'string' then
    return '"' .. v:gsub('[%z\1-\31\\"]', function(c)
      return string.format('\\u%04x', string.byte(c))
    end) .. '"'
  end
  if t ~= 'table' then return 'null' end
  local out = {}
  if #v > 0 or next(v) == nil then
    for i=1,#v do out[#out+1] = encode(v[i]) end
    return '[' .. table.concat(out, ',') .. ']'
  end
  for k,x in pairs(v) do out[#out+1] = encode(tostring(k)) .. ':' .. encode(x) end
  return '{' .. table.concat(out, ',') .. '}'
end
local function snapshot()
  local s = {protocol=2, capabilities={'batch'}, executed=executed, frame=frame, turns=turns, wins=wins, won=won, units={}, rules={}, buttons={},action_error=action_error}
  if generaldata then
    s.world = generaldata.strings[WORLD]
    s.level = generaldata.strings[CURRLEVEL]
    s.name = generaldata.strings[LEVELNAME]
    s.width,s.height = roomsizex,roomsizey
    s.ignore = generaldata.values[IGNORE]
    s.auto = generaldata5.values[AUTO_ON]
  end
  if editor then s.menu = editor.strings[MENU] end
  if editor2 then
    s.selected = editor2.strings[MENUOPTION]
    s.menu_x,s.menu_y = editor2.values[MENU_XPOS],editor2.values[MENU_YPOS]
  end
  if generaldata2 then
    s.in_menu = generaldata2.values[INMENU]
    s.paused = generaldata2.values[INPAUSEMENU]
    s.no_player = generaldata2.values[NOPLAYER]
  end
  s.undo_depth = math.max(0,#(undobuffer or {})-1)
  for _,u in ipairs(units or {}) do
    local props = {}
    local name = u.strings[UNITNAME]
    local x,y = u.values[XPOS],u.values[YPOS]
    for _,p in ipairs({'you','you2','win','push','stop','sink','defeat','hot','melt','float','move','open','shut','select','weak','pull','swap','tele','shift'}) do
      if hasfeature(name,'is',p,u.fixed,x,y) then props[#props+1] = p end
    end
    s.units[#s.units+1] = {id=u.values[ID],name=name,x=x,y=y,dir=u.values[DIR],type=u.strings[UNITTYPE],properties=props,level=u.strings[U_LEVELFILE],completed=u.values[COMPLETED]}
  end
  for _,v in ipairs(features or {}) do
    s.rules[#s.rules+1] = {words=v[1],conditions=v[2]}
  end
  local menu = menufuncs and menufuncs[s.menu]
  if menu and menu.structure then
    local structure = menu.structure[generaldata.strings[BUILD]] or menu.structure[1] or {}
    s.menu_structure = structure
    local seen = {}
    for y,row in ipairs(structure) do
      for x,cell in ipairs(row) do
        for _,name in ipairs(cell) do
          if not seen[name] then
            seen[name] = true
            for _,id in ipairs(MF_getbutton(name)) do
              local b = mmf.newObject(id)
              s.buttons[#s.buttons+1] = {name=name,text=b.strings[BUTTONTEXT],disabled=b.values[BUTTON_DISABLED],x=x-1,y=y-1}
            end
          end
        end
      end
    end
  end
  return s
end
local function respond(id)
  local good,s = pcall(snapshot)
  if not good then s = {protocol=2,error=tostring(s),frame=frame} end
  s.request_id = id
  -- The engine prefixes lang files with Data/Languages/. Temporarily select
  -- an isolated telemetry INI, then restore the real language on every path.
  local stored,err = pcall(function()
    MF_setfile('lang','baba_mcp/state.ini')
    MF_store('lang','baba_mcp','state',encode(s))
  end)
  local restored = pcall(MF_setfile,'lang','lang_' .. generaldata.strings[LANG] .. '.txt')
  if not stored or not restored then
    failed = true
    print('BABA_MCP transport disabled: ' .. tostring(err))
  end
end
local function advance_batch()
  local q = pending
  if not q then return end
  if not MF_findfile(path .. 'request.lua') then pending=nil; return end
  local action = q.actions[executed+1]
  local request = {op='move',key=action}
  if action == 'undo' then request={op='undo'} end
  local ok,err = pcall(dispatch,request)
  if ok then executed=executed+1 else action_error=tostring(err) end
  if not ok or executed >= #q.actions or won
    or generaldata.strings[WORLD] ~= q.world or generaldata.strings[CURRLEVEL] ~= q.level
    or editor.strings[MENU] ~= 'ingame' or generaldata2.values[INPAUSEMENU] ~= 0
    or generaldata.values[IGNORE] ~= 0 or (q.expects_player and generaldata2.values[NOPLAYER] ~= 0) then
    pending=nil
    respond(q.id)
  end
end
local function tick()
  frame=frame+1
  if failed or not generaldata then return end
  if pending then advance_batch(); return end
  if frame % 3 ~= 0 or not MF_findfile(path .. 'request.lua') then return end
  local ok,request=pcall(dofile,path .. 'request.lua')
  if not ok or type(request) ~= 'table' or type(request.id) ~= 'string' or request.id == last_request then return end
  last_request=request.id
  action_error=nil
  executed=0
  if request.op == 'batch' then
    local allowed={up=true,down=true,left=true,right=true,idle=true,undo=true}
    if type(request.actions) ~= 'table' or #request.actions < 1 or #request.actions > 64 then
      action_error='Expected 1..64 batch actions'
    else
      for _,action in ipairs(request.actions) do
        if not allowed[action] then action_error='Invalid batch action'; break end
      end
    end
    if action_error then respond(request.id); return end
    pending={id=request.id,actions=request.actions,world=generaldata.strings[WORLD],level=generaldata.strings[CURRLEVEL],expects_player=(#getunitswitheffect('you',true) > 0 or #getunitswitheffect('you2',true) > 0)}
    advance_batch()
  else
    local applied,err=pcall(dispatch,request)
    if not applied then action_error=tostring(err) end
    respond(request.id)
  end
end
table.insert(mod_hook_functions.always,function()
  local ok,err = pcall(tick)
  if not ok then failed=true; print('BABA_MCP disabled: ' .. tostring(err)) end
end)
table.insert(mod_hook_functions.level_start,function() won=false; turns=0 end)
table.insert(mod_hook_functions.level_win,function() won=true; wins=wins+1 end)
table.insert(mod_hook_functions.turn_end,function() turns=turns+1 end)
