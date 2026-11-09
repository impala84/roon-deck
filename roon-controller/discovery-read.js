'use strict';
const model = require('./discovery-model');
const namespace = 'Sooloos.Broker.Api';
async function waitFor(read, timeoutMs = 5000) {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    const value = read();
    if (value !== undefined) return value;
    if (Date.now() >= deadline) throw new Error('Discover data did not finish loading');
    await new Promise(resolve => setTimeout(resolve, 25));
  }
}
// Wait for the requested graph, not an arbitrary one-second sleep. Referenced
// objects arrive asynchronously after the RPC reply, including image metadata.
async function waitForGraph(graph, root) {
  return waitFor(() => {
    const seen = new Set();
    const ready = value => {
      if (!value || typeof value !== 'object' || Buffer.isBuffer(value)) return true;
      if (value.$ref !== undefined) {
        const key = String(value.$ref); if (seen.has(key)) return true;
        seen.add(key); const object = graph.getObject(BigInt(value.$ref));
        return !!object && ready(object.fields);
      }
      if (value.fields && value.oid !== undefined) return ready(value.fields);
      if (Array.isArray(value)) return value.every(ready);
      if (value.$count !== undefined && (!Array.isArray(value.$items) || value.$items.length < value.$count)) return false;
      return Object.entries(value).filter(([key]) => key === '$items' || /::(Album|SeedAlbum|Albums|Tracks|Image|Avatar|Images|Data|PerformerMixDescription|GenreMixDescription|Touchstones)$/.test(key)).every(([,item])=>ready(item));
    };
    return ready(root) ? true : undefined;
  });
}
async function waitForPreview(graph, root, limit) {
  return waitFor(() => {
    const object = model.resolve(graph, root);
    if (!object) return undefined;
    const count = Number(model.field(object, '$count'));
    const values = model.list(graph, object, limit);
    const expected = Number.isSafeInteger(count) && count >= 0 ? Math.min(count, limit) : limit;
    if (expected === 0) return [];
    return values.length >= expected && values.every(value => value && waitPreviewObject(graph, value)) ? values : undefined;
  });
}
function waitPreviewObject(graph, value) {
  const seen = new Set();
  const ready = current => {
    if (!current || typeof current !== 'object' || Buffer.isBuffer(current)) return true;
    if (current.$ref !== undefined) {
      const key = String(current.$ref); if (seen.has(key)) return true; seen.add(key);
      const object = graph.getObject(BigInt(current.$ref)); return !!object && ready(object.fields);
    }
    if (current.fields && current.oid !== undefined) return ready(current.fields);
    if (Array.isArray(current)) return current.every(ready);
    return Object.entries(current).filter(([key]) => key === '$items' || /::(Album|SeedAlbum|Albums|Image|Avatar|Images|Data|PerformerMixDescription|GenreMixDescription|Touchstones)$/.test(key)).every(([,item]) => ready(item));
  };
  return ready(value);
}
async function recentlyAdded(client, sdk) {
  const {Arg, buildArgs, BinaryWriter} = sdk;
  // Installed API metadata: AlbumOrdering.ImportDate=1, Descending=2.
  const ordering = client.structArg(`${namespace}.AlbumQueryOrdering`, [
    {name:'Ordering',propType:9,value:buildArgs([Arg.enum_(1)])},
    {name:'Direction',propType:9,value:buildArgs([Arg.enum_(2)])}]);
  const criteria = client.structArg(`${namespace}.AlbumQueryCriteria`, [{name:'Ordering',propType:23,value:ordering}]);
  const pageSize = 12;
  const params = client.structArg(`${namespace}.VirtualQueryParameters`, [{name:'PageSize',propType:0,value:new BinaryWriter().integer(pageSize).toBuffer()}]);
  const result = await client.remoting.callMethod(client.serviceOid('Library'),
    `${namespace}.Library::VirtualAlbumQuery(System.Sooid, ${namespace}.AlbumQueryCriteria, ${namespace}.VirtualQueryParameters, Base.ResultCallback<${namespace}.VirtualAlbumLiteQuery>)`,
    Buffer.concat([buildArgs([Arg.sooid(client.profile())]),criteria,params]));
  if (!result.success) throw new Error('Recently added albums are unavailable');
  const root = client.graph.decodeReturnValue(Uint8Array.from(result.payload));
  if (root?.$ref === undefined) throw new Error('Invalid album query');
  const oid = BigInt(root.$ref), type = `${namespace}.VirtualAlbumLiteQuery`;
  let retained = false;
  try {
    const count = await waitFor(() => model.field(client.graph.getObject(oid),'Count'));
    if (!Number.isSafeInteger(count) || count < 0) throw new Error('Invalid album count');
    if (!count) return {items:[],total:0};
    const before = new Set(client.graph.objects.keys());
    const page = await client.remoting.callMethod(oid,`${type}::RetainPage(int, Base.ResultCallback)`,buildArgs([Arg.int(0)]));
    if (!page.success) throw new Error('Album page unavailable');
    retained = true;
    // A fresh, isolated worker retains just one page. Page elements are pushed
    // in query order; never collect unrelated AlbumLite objects from the graph.
    const elements = await waitFor(() => {
      const values = [...client.graph.objects.values()].filter(o => !before.has(o.oid) && o.typeName === `${namespace}.VirtualQueryElement<${namespace}.AlbumLite>`);
      const page = values.slice(0,pageSize);
      return page.length >= Math.min(count,pageSize) && page.every(o=>model.field(o,'Data') && model.item(client.graph,model.field(o,'Data'))) ? page : undefined;
    });
    await waitForGraph(client.graph,{$items:elements.map(o=>model.field(o,'Data'))});
    const items = elements.map(o=>model.item(client.graph,model.field(o,'Data')));
    if (items.some(item=>!item)) throw new Error('Album metadata incomplete');
    return {items,total:count};
  } finally {
    if (retained) client.remoting.callMethodNoReply(oid,`${type}::ReleasePage(int, Base.ResultCallback)`,buildArgs([Arg.int(0)]));
    client.remoting.callMethodNoReply(oid,`${type}::Dispose()`,Buffer.alloc(0));
  }
}
async function dailyPicks(client, sdk, time) {
  const {BinaryWriter, Arg, buildArgs} = sdk;
  const type = `${namespace}.DailyPicksParameters`;
  const fields = [{name: `string ${type}::LocalTime`, propType: 20, value: new BinaryWriter().string(time).toBuffer()},
    ...['OverrideCache', 'RecentlyAddedOnly', 'NewReleasesOnly'].map(name => ({name: `bool ${type}::${name}`, propType: 2, value: buildArgs([Arg.bool(false)])}))];
  const args = buildArgs([Arg.sooid(client.profile())]);
  const current = await client.remoting.callMethod(client.serviceOid('Library'),
    `${namespace}.Library::GetDailyPicks(System.Sooid, ${type}, Base.ResultCallback<${namespace}.DataList<${namespace}.DailyPicksBox>>)`,
    Buffer.concat([args, client.structArg(type, fields)]));
  if (current.status !== 'MissingMethod') return current;
  // Older server signature remains supported; no brute-force signature loop.
  return client.remoting.callMethod(client.serviceOid('Library'),
    `${namespace}.Library::GetDailyPicks(System.Sooid, string, bool, Base.ResultCallback<${namespace}.DataList<${namespace}.DailyPicksBox>>)`,
    Buffer.concat([args, buildArgs([Arg.str(time), Arg.bool(false)])]));
}
async function readDiscovery(client, sdk, section, id) {
  const {Arg, buildArgs, exportPlayHistory} = sdk;
  const call = (method, args, result) => client.remoting.callMethod(client.serviceOid('Library'), `${namespace}.Library::${method}(System.Sooid, ${result})`, args);
  let result;
  if (section === 'added') return recentlyAdded(client,sdk);
  if (section === 'recent') {
    const history = await exportPlayHistory(client, {limit: 200, pageSize: 100, timeoutMs: 6000});   // every track played is an event, so many events make few albums
    return {items: model.recentAlbums(client.graph, history.events, 40)};
  }
  if (section === 'picks') {
    result = await dailyPicks(client, sdk, new Date().toISOString());
    if (!result.success) throw new Error('Personalised recommendations are unavailable in this Roon version');
    const root = client.graph.decodeReturnValue(Uint8Array.from(result.payload));
    await waitForPreview(client.graph, root, 3);
    const groups = model.picks(client.graph, root, 3, 6);
    return {items:[],groups};
  }
  if (section === 'daily') {
    result = await client.remoting.callMethod(client.serviceOid('Library'),
      `${namespace}.Library::GetMixes(System.Sooid, string, Base.ResultCallback<${namespace}.DataList<${namespace}.Mix>>)`,
      buildArgs([Arg.sooid(client.profile()), Arg.str(new Date().toISOString())]));
    if (!result.success) throw new Error('Daily mixes are unavailable in this Roon version');
    const mixRoot = client.graph.decodeReturnValue(Uint8Array.from(result.payload));
    await waitForPreview(client.graph, mixRoot, 6);
    return {items: model.mixes(client.graph, mixRoot, 6)};
  }
  if (section === 'mix') {
    if (!/^[a-f0-9]{2,160}$/i.test(id || '') || id.length % 2) throw new Error('Invalid mix reference');
    result = call('GetMix', buildArgs([Arg.sooid(Buffer.from(id, 'hex'))]), `Base.ResultCallback<${namespace}.Mix>`);
    result = await result;
    if (!result.success) throw new Error('This mix is no longer available');
    const root = client.graph.decodeReturnValue(Uint8Array.from(result.payload));
    if (!root?.$ref) throw new Error('Invalid mix result');
    result = await client.remoting.callMethod(BigInt(root.$ref), `${namespace}.Mix::GetItems(Base.ResultCallback<${namespace}.DataList<${namespace}.MixItem>>)`, Buffer.alloc(0));
    if (!result.success) throw new Error('The mix track list could not be loaded');
    const tracks = client.graph.decodeReturnValue(Uint8Array.from(result.payload));
    await waitForGraph(client.graph, tracks);
    return {mix: model.mixes(client.graph, {$items:[root]}, 1)[0] || null, items: model.list(client.graph, tracks, 20).flatMap(group => model.list(client.graph, model.field(group, 'Tracks'), 5).map(track => model.item(client.graph, track, 'track'))).filter(Boolean), total: Number(model.field(model.resolve(client.graph, tracks), '$count') || 0)};
  }
  if (section !== 'releases') throw new Error('Unknown Discover section');
  result = await call('GetNewReleasesForYou', buildArgs([Arg.sooid(client.profile())]), `Base.ResultCallback<${namespace}.DataList<${namespace}.AlbumWithExtras>>`);
  if (!result.success) throw new Error('New Releases are unavailable in this Roon version');
  const root = client.graph.decodeReturnValue(Uint8Array.from(result.payload));
  await waitForPreview(client.graph, root, 8);
  return {items: model.list(client.graph, root, 8).map(wrapper => model.item(client.graph, model.field(wrapper, 'Album'))).filter(Boolean)};
}
module.exports = {dailyPicks, readDiscovery, waitFor, waitForGraph, waitForPreview, recentlyAdded};
