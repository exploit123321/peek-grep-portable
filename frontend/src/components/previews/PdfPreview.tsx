import React from 'react';

// The PDF viewer in WebView2 searches for the text after #search= and shows the first hit
export const PdfPreview: React.FC<{ rawUrl: string; filename: string; query?: string }> = ({ rawUrl, filename, query }) => {
  const src = query?.trim() ? `${rawUrl}#search=${encodeURIComponent(query.trim())}` : rawUrl;
  return <iframe src={src} className="w-full h-full border-0 bg-[#1b1b22]" title={filename} />;
};
