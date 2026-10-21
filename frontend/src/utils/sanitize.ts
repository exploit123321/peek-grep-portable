// Remove active content from HTML that comes from user files (Markdown output, EPUB chapters).
// The page CSP already blocks inline scripts. This is a second layer.

const DROP_TAGS = new Set([
  'script', 'style', 'iframe', 'frame', 'frameset', 'object', 'embed', 'link', 'meta', 'base',
  'form', 'button', 'textarea', 'select', 'template', 'noscript', 'svg', 'math', 'video', 'audio',
]);

const URL_ATTRS = new Set(['href', 'src', 'xlink:href', 'action', 'formaction', 'poster', 'srcset']);

export function sanitizeHtml(html: string): string {
  const doc = new DOMParser().parseFromString(`<body>${html}</body>`, 'text/html');
  const walk = (node: Element) => {
    for (const child of Array.from(node.children)) {
      const tag = child.tagName.toLowerCase();
      if (DROP_TAGS.has(tag)) {
        child.remove();
        continue;
      }
      if (tag === 'input' && (child as HTMLInputElement).type !== 'checkbox') {
        child.remove();
        continue;
      }
      for (const attr of Array.from(child.attributes)) {
        const name = attr.name.toLowerCase();
        const value = attr.value.trim().toLowerCase();
        if (name.startsWith('on') || name === 'style' && /expression|url\s*\(/.test(value)) {
          child.removeAttribute(attr.name);
        } else if (URL_ATTRS.has(name)) {
          const safeImage = name === 'src' && tag === 'img' && value.startsWith('data:image/');
          if (value.startsWith('javascript:') || value.startsWith('vbscript:') || (value.startsWith('data:') && !safeImage)) {
            child.removeAttribute(attr.name);
          }
        }
      }
      if (tag === 'input') child.setAttribute('disabled', '');
      walk(child);
    }
  };
  walk(doc.body);
  return doc.body.innerHTML;
}
