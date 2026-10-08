/**
 * Save a rendered chart as a PNG.
 *
 * Recharts draws SVG; this serialises the first `<svg>` inside a container,
 * paints it onto a canvas over the app's background colour — a transparent PNG
 * of white-on-nothing text is unreadable in every viewer — and triggers the
 * download.
 *
 * Shared by the panels that offer an export, so the exported images agree
 * about size and background (`NEXT_STEPS.md` §60).
 */
// Downloads the first SVG found inside a container div as a PNG.
export function downloadChartAsPng(containerRef, filename) {
  if (!containerRef.current) return;
  const svg = containerRef.current.querySelector('svg');
  if (!svg) return;
  const svgData = new XMLSerializer().serializeToString(svg);
  const canvas  = document.createElement('canvas');
  const bbox    = svg.getBoundingClientRect();
  canvas.width  = bbox.width  || 800;
  canvas.height = bbox.height || 400;
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = '#0f1923';
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  const img = new Image();
  img.onload = () => {
    ctx.drawImage(img, 0, 0);
    const a = document.createElement('a');
    a.href     = canvas.toDataURL('image/png');
    a.download = filename;
    a.click();
  };
  img.src = 'data:image/svg+xml;base64,' + btoa(unescape(encodeURIComponent(svgData)));
}
