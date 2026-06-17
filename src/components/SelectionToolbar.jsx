import React from 'react';

/**
 * Floating toolbar for rectangle / polygon region selection.
 *
 * Props:
 *   selectionMode    {string|null}  'rectangle' | 'polygon' | null
 *   setSelectionMode {fn}
 *   selectedRegion   {object|null}
 *   clearSelection   {fn}
 */
export function SelectionToolbar({ selectionMode, setSelectionMode, selectedRegion, clearSelection }) {
  return (
    <>
      {/* Tool buttons */}
      <div style={{ position: 'absolute', top: '124px', right: '12px', zIndex: 1001, display: 'flex', flexDirection: 'column', gap: '6px' }}>
        <button
          title="Rectangle selection"
          onClick={() => setSelectionMode(m => m === 'rectangle' ? null : 'rectangle')}
          style={{ width: '44px', height: '44px', background: selectionMode === 'rectangle' ? 'rgba(52,152,219,0.95)' : 'rgba(44,62,80,0.95)', border: 'none', borderRadius: '8px', color: 'white', cursor: 'pointer', fontSize: '20px', display: 'flex', alignItems: 'center', justifyContent: 'center', boxShadow: '0 4px 12px rgba(0,0,0,0.3)', transition: 'all 0.2s' }}>
          ⬜
        </button>
        <button
          title="Polygon selection"
          onClick={() => setSelectionMode(m => m === 'polygon' ? null : 'polygon')}
          style={{ width: '44px', height: '44px', background: selectionMode === 'polygon' ? 'rgba(52,152,219,0.95)' : 'rgba(44,62,80,0.95)', border: 'none', borderRadius: '8px', color: 'white', cursor: 'pointer', fontSize: '20px', display: 'flex', alignItems: 'center', justifyContent: 'center', boxShadow: '0 4px 12px rgba(0,0,0,0.3)', transition: 'all 0.2s' }}>
          🔷
        </button>
        {selectedRegion && (
          <button
            title="Clear selection"
            onClick={clearSelection}
            style={{ width: '44px', height: '44px', background: 'rgba(231,76,60,0.9)', border: 'none', borderRadius: '8px', color: 'white', cursor: 'pointer', fontSize: '18px', display: 'flex', alignItems: 'center', justifyContent: 'center', boxShadow: '0 4px 12px rgba(0,0,0,0.3)', transition: 'all 0.2s' }}>
            ✕
          </button>
        )}
      </div>

      {/* Draw mode indicator */}
      {selectionMode && (
        <div style={{ position: 'absolute', top: '60px', left: '50%', transform: 'translateX(-50%)', background: 'rgba(22,33,44,0.92)', color: 'white', padding: '8px 18px', borderRadius: '20px', fontSize: '13px', fontWeight: '600', zIndex: 1002, pointerEvents: 'none', whiteSpace: 'nowrap', boxShadow: '0 2px 12px rgba(0,0,0,0.4)', border: '1px solid rgba(52,152,219,0.5)' }}>
          {selectionMode === 'rectangle'
            ? '⬜ Click and drag to draw a rectangle'
            : '🔷 Click to add vertices · Double-click to close'}
        </div>
      )}
    </>
  );
}
