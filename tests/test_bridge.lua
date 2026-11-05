-- Run outside the game: lua tests/bridge_test.lua bridge.lua
local source = arg[1] or 'bridge.lua'
local request = {id='state1',op='state'}
local writes, selected, moves, updates = {}, '', 0, 0
local function values() return setmetatable({},{__index=function() return 0 end}) end
local function strings() return setmetatable({},{__index=function() return '' end}) end
XPOS,YPOS,DIR,ID,COMPLETED=4,5,6,21,12
UNITNAME,UNITTYPE,U_LEVELFILE=3,2,4
WORLD,CURRLEVEL,LEVELNAME,LANG=2,3,4,8
IGNORE,AUTO_ON,INPAUSEMENU,INMENU,NOPLAYER=19,16,7,6,3
MENU,MENUOPTION,MENU_XPOS,MENU_YPOS=3,3,2,3
BUTTONTEXT,BUTTON_DISABLED=5,13
generaldata={values=values(),strings=strings()}
generaldata.strings[LANG]='en'
generaldata2={values=values()};generaldata5={values=values()}
editor={strings=strings()};editor.strings[MENU]='ingame'
editor2={values=values(),strings=strings()}
roomsizex,roomsizey=10,10
units={{values=values(),strings=strings(),fixed=5}}
units[1].strings[UNITNAME]='baba';units[1].strings[UNITTYPE]='object'
units[1].values[XPOS]=2
features={{{'baba','is','you'},{}}};undobuffer={{}}
menufuncs={}
function hasfeature(n,v,p) return p=='you' end
function getunitswitheffect(name) return {} end
function MF_findfile() return true end
function MF_setfile(_,name) selected=name end
function MF_store(_,_,_,text) writes[#writes+1]=text end
function command(key) moves=moves+1;units[1].values[XPOS]=3 end
function undo() units[1].values[XPOS]=2 end
function code() end
function MF_update() updates=updates+1 end
mod_hook_functions={always={},level_start={},level_win={},turn_end={}}
local original_dofile=dofile
original_dofile(source)
-- Simulate the engine sandbox. The bridge must never rely on these.
io=nil;os=nil
function dofile() return request end
local function tick() for _=1,3 do mod_hook_functions.always[1]() end end
tick();assert(#writes==1);assert(writes[1]:find('"request_id":"state1"',1,true))
assert(selected=='lang_en.txt')
request={id='move1',op='move',key='left'};tick();assert(moves==1)
tick();assert(moves==1,'duplicate request executed twice')
request={id='undo1',op='undo'};tick();assert(updates==1 and units[1].values[XPOS]==2)
request={id='invalid',op='eval',key='whatever'};tick();assert(writes[#writes]:find('action_error',1,true))
assert(selected=='lang_en.txt')
generaldata2.values[NOPLAYER]=1 -- Maps have no YOU but cursor control remains valid.
request={id='batch1',op='batch',actions={'left','left','undo'}}
local previous_writes=#writes
tick();tick()
assert(moves==3 and updates==2)
assert(#writes==previous_writes+1,'batch must emit one final snapshot')
assert(writes[#writes]:find('"executed":3',1,true))
request={id='batchbad',op='batch',actions={'left','eval'}}
tick();assert(moves==3,'validate every action before starting')
function command(key)
  moves=moves+1
  mod_hook_functions.level_win[1]()
end
request={id='batchwin',op='batch',actions={'left','left','left'}}
tick();tick()
assert(moves==4,'batch must stop on first victory')
assert(writes[#writes]:find('"executed":1',1,true))
print('bridge sandbox, native dispatch, batch, deduplication, undo, error containment: OK')
