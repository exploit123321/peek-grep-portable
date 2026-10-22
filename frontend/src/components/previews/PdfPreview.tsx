import React from 'react';

// The PDF viewer in WebView2 searches for the text after #search= and shows the first hit
// (plain text only: wildcards and several terms work in the other previews)
export const PdfPreview: React.FC<{ rawUrl: string; filename: string; search?: string }> = ({ rawUrl, filename, search }) => {
  const src = search?.trim() ? `${rawUrl}#search=${encodeURIComponent(search.trim())}` : rawUrl;
  return <iframe key={src} src={src} className="w-full h-full border-0 bg-[#1b1b22]" title={filename} />;
};
