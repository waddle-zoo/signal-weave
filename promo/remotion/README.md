# SignalWeave Remotion film

This composition wraps the real HTML demo recording in a deterministic motion-design layer. It keeps the product pixels and readable text intact, then adds Apple-style camera movement: focused pushes, page flips, soft washes, graph emphasis, and a restrained progress rail.

## Render

```bash
npm install
npm run render
```

On macOS with Google Chrome installed, the local render command avoids downloading another browser:

```bash
npm run render:mac
```

Open Remotion Studio while iterating:

```bash
npm run studio
```

The source recording lives at `public/signalweave-page-recording.mp4`. Replace it with a new page capture when the HTML demo changes.
