import React from 'react';
import { Square, Hexagon, X } from 'lucide-react';
import { IconButton } from './ui/IconButton';
import { t } from '../theme';

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
      <div style={{ position: 'absolute', top: '124px', right: '12px', zIndex: 1001, display: 'flex', flexDirection: 'column', gap: '6px', transition: t.transition }}>
        <IconButton
          label="Rectangle selection"
          aria-pressed={selectionMode === 'rectangle'}
          active={selectionMode === 'rectangle'}
          size={44}
          onClick={() => setSelectionMode(m => m === 'rectangle' ? null : 'rectangle')}
          style={{ background: selectionMode === 'rectangle' ? t.accent : t.panel }}>
          <Square size={20} />
        </IconButton>
        <IconButton
          label="Polygon selection"
          aria-pressed={selectionMode === 'polygon'}
          active={selectionMode === 'polygon'}
          size={44}
          onClick={() => setSelectionMode(m => m === 'polygon' ? null : 'polygon')}
          style={{ background: selectionMode === 'polygon' ? t.accent : t.panel }}>
          <Hexagon size={20} />
        </IconButton>
        {selectedRegion && (
          <IconButton
            label="Clear selection"
            danger
            size={44}
            onClick={clearSelection}
          >
            <X size={18} />
          </IconButton>
        )}
      </div>

      {/* Draw mode indicator */}
      {selectionMode && (
        <div style={{ position: 'absolute', top: '60px', left: '50%', transform: 'translateX(-50%)', background: 'rgba(22,33,44,0.92)', color: 'white', padding: '8px 18px', borderRadius: '20px', fontSize: '13px', fontWeight: '600', zIndex: 1002, pointerEvents: 'none', whiteSpace: 'nowrap', boxShadow: '0 2px 12px rgba(0,0,0,0.4)', border: '1px solid rgba(52,152,219,0.5)' }}>
          {selectionMode === 'rectangle'
            ? 'Click and drag to draw a rectangle'
            : 'Click to add vertices · double-click to close'}
        </div>
      )}
    </>
  );
}
