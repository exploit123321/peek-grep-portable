// Search settings (the "search" block of data\settings.json). The server checks and stores
// them; these defaults are used until the settings have loaded.

export interface SearchOptions {
  enabled: boolean;
  default_scope: 'names' | 'text' | 'both';
  text_char: string;
  and_char: string;
  not_char: string;
  dash_mode: 'anywhere' | 'word_start';
  literal_char: string;
  quotes: boolean;
  group_open: string;
  group_close: string;
  list_char: string;
  param_char: string;
  date_order: 'dmy' | 'mdy' | 'ymd';
  comma_joins: boolean;
  extensions: boolean;
  exact_names: boolean;
  wildcards: boolean;
  names_include_folders: boolean;
  text_prefix: boolean;
  sort: 'best' | 'newest' | 'oldest' | 'name' | 'size';
  page_size: number;
  show_snippets: boolean;
  show_chips: boolean;
  groups_open: 'auto' | 'all' | 'none';
  search_delay_ms: number;
  paste_list: 'table' | 'groups' | 'text';
  list_where: 'names' | 'text';
  list_mode: 'groups' | 'together';
  preview_highlight: boolean;
  preview_jump: boolean;
  type_to_find: boolean;
}

export const DEFAULT_SEARCH_OPTIONS: SearchOptions = {
  enabled: true,
  default_scope: 'names',
  text_char: ':',
  and_char: '+',
  not_char: '-',
  dash_mode: 'anywhere',
  literal_char: '/',
  quotes: true,
  group_open: '[',
  group_close: ']',
  list_char: ',',
  param_char: ';',
  date_order: 'dmy',
  comma_joins: true,
  extensions: true,
  exact_names: true,
  wildcards: true,
  names_include_folders: false,
  text_prefix: true,
  sort: 'best',
  page_size: 60,
  show_snippets: true,
  show_chips: true,
  groups_open: 'auto',
  search_delay_ms: 110,
  paste_list: 'table',
  list_where: 'names',
  list_mode: 'groups',
  preview_highlight: true,
  preview_jump: true,
  type_to_find: true,
};

export interface SearchPreset {
  id: string;
  label: string;
  options: SearchOptions;
}

/** Can the list (groups or a+b) be written with these settings? */
export function canWriteLists(o: SearchOptions): boolean {
  return o.enabled && !!o.group_open && !!o.list_char && !!o.and_char;
}
