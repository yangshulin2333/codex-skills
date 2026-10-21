-- Read-only client terrain capture. No online Terrain/object property is written.
-- Each nonempty chunk preserves all 3 channels using exact numeric JSON RLE.
-- CAPTURE_CONFIG
assert(game.PlaceId == CONFIG.placeId and game.GameId == CONFIG.universeId, "Wrong client identity")
assert(CONFIG.terrain, "Bind explicit terrain scan bounds before this step")
assert(type(writefile)=="function" and type(readfile)=="function", "File APIs unavailable")
local H = game:GetService("HttpService")
local T = workspace.Terrain
local root = CONFIG.outputDirectory .. "/terrain/" .. CONFIG.terrain.captureName
assert(not isfolder(root), "Capture already exists; preserve it before rerunning")
makefolder(root)
makefolder(root.."/chunks")
makefolder(root.."/index")
local indexLines = {}
local function recordEntry(entry)
    local line = H:JSONEncode(entry)
    writefile(root..string.format("/index/chunk-%04d.json", entry.index), line)
    table.insert(indexLines, line .. "\n")
end
local scanMin = Vector3.new(table.unpack(CONFIG.terrain.min))
local scanMax = Vector3.new(table.unpack(CONFIG.terrain.maxExclusive))
local chunkStuds = Vector3.new(table.unpack(CONFIG.terrain.chunkStuds))
local resolution = CONFIG.terrain.resolution
local function vec(v) return {v.X,v.Y,v.Z} end
local function countCells()
    local ok,value=pcall(function() return T:CountCells() end)
    return {ok=ok,value=ok and value or nil,error=not ok and tostring(value) or nil}
end
local report = {
    schema="codex-terrain-channel-capture-v1",placeId=game.PlaceId,universeId=game.GameId,
    started=os.time(),streamingEnabled=workspace.StreamingEnabled,
    scope="Every voxel in the explicit scan box; this does not exhaust Terrain.MaxExtents or the whole world",
    bounds={min=vec(scanMin),maxExclusive=vec(scanMax),units="studs",resolution=resolution},
    chunkStuds=vec(chunkStuds),channels={"SolidMaterial","SolidOccupancy","LiquidOccupancy"},
    CountCellsBefore=countCells(),CountCellsNote="Official CountCells is approximate; comparison is an indicator, not a proof of global completeness",
    totals={plannedChunks=0,completedChunks=0,failedChunks=0,nonemptyChunks=0,emptyChunks=0,
            scannedVoxels=0,nonemptyCells=0,solidCells=0,liquidCells=0,nondefaultCells=0},
    materials={},filledMin=nil,filledMaxExclusive=nil,
    index="chunk-index.jsonl",chunkFormat="codex-terrain-rle-v2",gameObjectsModified=false,
}
local valueCache={}
local function materialValue(material)
    local value=valueCache[material]
    if value==nil then
        value=material.Value
        valueCache[material]=value
        report.materials[tostring(value)]={name=material.Name,value=value}
    end
    return value
end
local airValue=Enum.Material.Air.Value
local countX=(scanMax.X-scanMin.X)/chunkStuds.X
local countY=(scanMax.Y-scanMin.Y)/chunkStuds.Y
local countZ=(scanMax.Z-scanMin.Z)/chunkStuds.Z
assert(countX==math.floor(countX) and countY==math.floor(countY) and countZ==math.floor(countZ), "Scan bounds must align with chunks")
report.totals.plannedChunks=countX*countY*countZ
writefile(root.."/capture-start.json",H:JSONEncode(report))
writefile(root.."/chunk-index.jsonl","")
local filledMin,filledMax
local lastProgress=os.clock()
local function progress(force)
    if force or os.clock()-lastProgress>=5 or report.totals.completedChunks%16==0 then
        lastProgress=os.clock()
        writefile(root.."/capture-progress.json",H:JSONEncode({placeId=game.PlaceId,universeId=game.GameId,
            updated=os.time(),totals=report.totals,elapsedSeconds=os.time()-report.started}))
        print("ARCHIVE_TERRAIN_CAPTURE_PROGRESS "..H:JSONEncode(report.totals))
    end
end
local function recordChunk(origin,size,number)
    local entry={index=number,origin=vec(origin),sizeInCells=vec(size),method="ReadVoxelChannels"}
    local region=Region3.new(origin,origin+size*resolution)
    local ok,channels=pcall(function()
        return T:ReadVoxelChannels(region,resolution,{"SolidMaterial","SolidOccupancy","LiquidOccupancy"})
    end)
    if not ok then
        entry.ok=false
        entry.error=tostring(channels):sub(1,1000)
        report.totals.failedChunks+=1
        recordEntry(entry)
        return
    end
    local mats,solid,liquid=channels.SolidMaterial,channels.SolidOccupancy,channels.LiquidOccupancy
    assert(type(mats)=="table" and type(solid)=="table" and type(liquid)=="table", "ReadVoxelChannels returned incomplete channels")
    local dims=mats.Size or Vector3.new(#mats,#mats[1],#mats[1][1])
    assert(dims.X==size.X and dims.Y==size.Y and dims.Z==size.Z, "Voxel dimensions differ from requested chunk")
    local runs={}
    local lastM,lastS,lastL,runLength=nil,nil,nil,0
    local nonempty,solidCount,liquidCount,nondefault=0,0,0,0
    local chunkMin,chunkMax,dataMin,dataMax
    local materialNames={}
    local function flush()
        if runLength>0 then
            table.insert(runs,runLength)
            table.insert(runs,lastM)
            table.insert(runs,lastS)
            table.insert(runs,lastL)
        end
    end
    for x=1,dims.X do
        local mx,sx,lx=mats[x],solid[x],liquid[x]
        for y=1,dims.Y do
            local my,sy,ly=mx[y],sx[y],lx[y]
            for z=1,dims.Z do
                local material=my[z]
                local m,s,l=materialValue(material),sy[z],ly[z]
                assert(type(s)=="number" and type(l)=="number", "Non-numeric occupancy returned")
                materialNames[tostring(m)]=report.materials[tostring(m)]
                local hasSolid=m~=airValue and s>0
                local hasLiquid=l>0
                local corner
                if m~=airValue or s~=0 or l~=0 then
                    nondefault+=1
                    corner=origin+Vector3.new((x-1)*resolution,(y-1)*resolution,(z-1)*resolution)
                    dataMin=dataMin and dataMin:Min(corner) or corner
                    dataMax=dataMax and dataMax:Max(corner+Vector3.one*resolution) or (corner+Vector3.one*resolution)
                end
                if hasSolid then solidCount+=1 end
                if hasLiquid then liquidCount+=1 end
                if hasSolid or hasLiquid then
                    nonempty+=1
                    chunkMin=chunkMin and chunkMin:Min(corner) or corner
                    chunkMax=chunkMax and chunkMax:Max(corner+Vector3.one*resolution) or (corner+Vector3.one*resolution)
                end
                if m~=lastM or s~=lastS or l~=lastL then
                    flush()
                    lastM,lastS,lastL,runLength=m,s,l,1
                else runLength+=1 end
            end
        end
    end
    flush()
    local voxels=dims.X*dims.Y*dims.Z
    local sumRuns=0
    for i=1,#runs,4 do sumRuns+=runs[i] end
    assert(sumRuns==voxels, "RLE does not preserve all requested voxels")
    entry.ok=true
    entry.voxels=voxels
    entry.nonemptyCells=nonempty
    entry.solidCells=solidCount
    entry.liquidCells=liquidCount
    entry.nondefaultCells=nondefault
    entry.empty=nondefault==0
    if nondefault>0 then
        local name=string.format("chunks/chunk-%04d.json",number)
        local payload={schema="codex-terrain-rle-v2",origin=vec(origin),resolution=resolution,size=vec(dims),
            order="x-major,y-middle,z-fastest",fields={"runLength","Enum.Material.Value","SolidOccupancy","LiquidOccupancy"},
            method="ReadVoxelChannels",runs=runs,materials=materialNames,nonemptyCells=nonempty,
            solidCells=solidCount,liquidCells=liquidCount,nondefaultCells=nondefault,
            filledMin=chunkMin and vec(chunkMin) or nil,filledMaxExclusive=chunkMax and vec(chunkMax) or nil,
            dataMin=vec(dataMin),dataMaxExclusive=vec(dataMax),
            occupancies="Original numeric values without rounding or quantization"}
        local encoded=H:JSONEncode(payload)
        writefile(root.."/"..name,encoded)
        entry.file=name
        entry.bytes=#encoded
        entry.runs=#runs/4
        entry.filledMin=chunkMin and vec(chunkMin) or nil
        entry.filledMaxExclusive=chunkMax and vec(chunkMax) or nil
        report.totals.nonemptyChunks+=1
        if chunkMin then filledMin=filledMin and filledMin:Min(chunkMin) or chunkMin end
        if chunkMax then filledMax=filledMax and filledMax:Max(chunkMax) or chunkMax end
    else
        -- Air values are deliberately represented only by this explicit index
        -- entry. A full-size empty JSON voxel table is never written to disk.
        report.totals.emptyChunks+=1
    end
    report.totals.scannedVoxels+=voxels
    report.totals.nonemptyCells+=nonempty
    report.totals.solidCells+=solidCount
    report.totals.liquidCells+=liquidCount
    report.totals.nondefaultCells+=nondefault
    recordEntry(entry)
end
local ok,message=xpcall(function()
    local number=0
    for ix=0,countX-1 do
        for iy=0,countY-1 do
            for iz=0,countZ-1 do
                assert(game.PlaceId==CONFIG.placeId and game.GameId==CONFIG.universeId, "Client moved to another game; capture stopped")
                number+=1
                local origin=scanMin+Vector3.new(ix*chunkStuds.X,iy*chunkStuds.Y,iz*chunkStuds.Z)
                recordChunk(origin,chunkStuds/resolution,number)
                report.totals.completedChunks+=1
                progress(false)
                task.wait()
            end
        end
    end
end,debug.traceback)
local indexText = table.concat(indexLines)
writefile(root.."/chunk-index.jsonl", indexText)
local indexVerified = readfile(root.."/chunk-index.jsonl") == indexText
report.finished=os.time()
report.elapsedSeconds=report.finished-report.started
report.CountCellsAfter=countCells()
report.stableCountIndicator=report.CountCellsBefore.ok and report.CountCellsAfter.ok
    and report.CountCellsBefore.value==report.CountCellsAfter.value or false
report.filledMin=filledMin and vec(filledMin) or nil
report.filledMaxExclusive=filledMax and vec(filledMax) or nil
report.completeExplicitBox=ok and indexVerified and #indexLines==report.totals.plannedChunks and report.totals.completedChunks==report.totals.plannedChunks and report.totals.failedChunks==0
report.completeWholeWorld=false
if report.CountCellsBefore.ok then
    report.nonemptyMinusApproxCount=report.totals.nonemptyCells-report.CountCellsBefore.value
    report.solidMinusApproxCount=report.totals.solidCells-report.CountCellsBefore.value
end
if not ok then report.error=tostring(message) end
progress(true)
writefile(root.."/capture-summary.json",H:JSONEncode(report))
writefile(root.."/capture-complete.txt",report.completeExplicitBox and "Explicit scan box complete; global completeness is not claimed" or "Capture incomplete; inspect capture-summary.json")
print("ARCHIVE_TERRAIN_CHANNEL_CAPTURE_FINISHED "..H:JSONEncode(report))
