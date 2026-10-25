# Roon library and favourite actions

## Evidence

The owner's official macOS Roon client was recorded on 5 October 2026 against
the real Core. TCP streams were reassembled, method declarations/calls decoded,
and server object updates replayed through RoonDeck's pinned object-graph reader.
Raw recordings remain private and are not shipped or committed.

Observed library-add:

```
Sooloos.Broker.Api.Library::AddToLibrary(Sooloos.Broker.Api.Profile, Sooloos.Broker.Api.AlbumBase)
```

Arguments are two session-local bare object references. There is no callback
or success reply. The same streaming AlbumLite subsequently receives a positive
`LibraryAlbumId`. Sending the command alone is not success.

Observed favourite and unfavourite:

```
Sooloos.Broker.Api.Library::FavoriteOrBan(System.Sooid, Sooloos.Broker.Api.AlbumBase, Sooloos.Broker.Api.FavoriteBanState, Base.ResultCallback)
```

Arguments are profile Sooid, album object reference, and enum 1 (favourite) or
0 (clear). The library edition's `IsFavorite` ProfileData<bool> updates to a
count/length-prefixed profile/true entry, then an empty map when cleared.
The streaming metadata edition is not a reliable source for favourite state.
`GetAlbumLite(long, Base.ResultCallback<AlbumLite>)`, also observed in the
recording, resolves the positive library ID to that edition.

## RoonDeck implementation

Live Core checks also verified this implementation adding Judas Priest's
Rocka Rolla (not-in-library → in-library, still unfavourited), and favouriting
then unfavouriting Dave Holland's Freedom Call: Sextet - Unity, restoring its
original state. Neither check changed playback.

`library-protocol.js` resolves the exact selected Zone → NowPlaying → current
TransportTrack → TrackLite → AlbumLite, using the TransportTrack's ProfileId
and matching Profile object. It never adds a fuzzy search result, never reuses
another session's object handles, and rechecks identity before mutation.

`library-state.js` runs bounded background workers, coalesces status reads,
caches status for 30 seconds, invalidates on track/Core changes, serialises
mutations, and replaces state only after Roon confirmation. No network request
runs on GTK's main thread. GTK shows + outside the library, an outline heart
inside the library, and a filled heart when favourited. Mutation errors are
visible. Unknown state disables the action rather than pretending it is absent.

Library removal is intentionally not exposed: clearing a favourite is not
removing an album, and no safe removal operation was established by these captures.

Verification must distinguish recorded official-client traffic, automated
controller tests, read-only checks on the live Core, and actual Pi touchscreen
mutation/layout checks. None substitutes for the others.
