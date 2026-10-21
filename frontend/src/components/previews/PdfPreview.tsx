import React from 'react';

export const PdfPreview: React.FC<{ rawUrl: string; filename: string }> = ({ rawUrl, filename }) => (
  <iframe src={rawUrl} className="w-full h-full border-0 bg-[#1b1b22]" title={filename} />
);
