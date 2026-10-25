// Drag a file out of the app into another one (Telegram, mail, Explorer), as if from Explorer.
// The desktop app does the real drag (Windows drag and drop with the file path), started while
// the mouse button is still down. In a plain browser, Chromium's "DownloadURL" drag is the fallback.

import type React from 'react';
import { desktop } from '../api';

const THRESHOLD = 6;

interface DragSource {
  paths: string[];
  /** For the browser fallback: the file's URL in this app (/api/raw?...) and its name */
  rawUrl?: string | null;
  filename?: string;
}

let dragging = false;
// The press that may become a drag. Here, not in the component: the list draws itself anew
// while the mouse moves (a closure would forget the press).
let start: { x: number; y: number; target: EventTarget } | null = null;
// The browser fallback's drag (a link to the file, not a file)
let linkDrag = false;

// A file let go over the app itself (a drag out that ends inside the window, or one from Explorer)
// would make the WebView open that file. The window is no place to drop: the cursor says so and
// letting go does nothing; only another app gets the file. Text dragged into a field still drops.
const refuseDrop = (e: DragEvent) => {
  if (!linkDrag && !e.dataTransfer?.types.includes('Files')) return;
  e.preventDefault();
  e.dataTransfer!.dropEffect = 'none';
};
if (typeof window !== 'undefined') {
  for (const type of ['dragenter', 'dragover', 'drop'] as const) window.addEventListener(type, refuseDrop);
}

export function fileDragProps(source: () => DragSource | null) {
  const native = !!desktop()?.drag_files;

  const props: Pick<React.HTMLAttributes<HTMLElement>, 'onPointerDown' | 'onPointerMove' | 'onPointerUp' | 'onDragStart' | 'onDragEnd'> & {
    draggable?: boolean;
  } = {
    onPointerDown: e => {
      start = e.button === 0 ? { x: e.clientX, y: e.clientY, target: e.currentTarget } : null;
    },
    onPointerUp: () => {
      start = null;
    },
    onPointerMove: e => {
      if (!native || !start || start.target !== e.currentTarget || dragging || !(e.buttons & 1)) return;
      if (Math.abs(e.clientX - start.x) + Math.abs(e.clientY - start.y) < THRESHOLD) return;
      const src = source();
      start = null;
      if (!src?.paths.length) return;
      dragging = true;
      desktop()!.drag_files!(src.paths).finally(() => {
        dragging = false;
      });
    },
  };
  if (!native) {
    props.draggable = true;
    props.onDragStart = e => {
      const src = source();
      if (!src?.rawUrl || !src.filename) return;
      const url = new URL(src.rawUrl, window.location.href).href;
      e.dataTransfer.setData('DownloadURL', `application/octet-stream:${src.filename}:${url}`);
      e.dataTransfer.setData('text/uri-list', url);
      e.dataTransfer.effectAllowed = 'copy';
      linkDrag = true;
    };
    props.onDragEnd = () => {
      linkDrag = false;
    };
  }
  return props;
}
