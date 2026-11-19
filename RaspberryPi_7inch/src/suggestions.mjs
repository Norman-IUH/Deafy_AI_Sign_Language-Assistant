const fold = value => value.normalize('NFD').replace(/\p{M}/gu, '').replace(/[đĐ]/g, 'd').toLowerCase().trim();

export function suggestions(items, query) {
  const search = fold(query);
  if (!search) return [];
  const rank = item => fold(item.text) === search ? 0 : fold(item.text).startsWith(search) ? 1 : 2;
  return items.filter(item => fold(item.text).includes(search))
    .sort((a, b) => rank(a) - rank(b) || a.text.localeCompare(b.text, 'vi')).slice(0, 6);
}
