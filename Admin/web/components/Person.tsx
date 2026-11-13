export function Person({ id, name, has_avatar, big }: { id: number; name: string; has_avatar: boolean; big?: boolean }) {
  const cls = big ? "avatar big" : "avatar";
  // eslint-disable-next-line @next/next/no-img-element
  if (has_avatar) return <img className={cls} src={`/api/admin/users/${id}/avatar`} alt="" />;
  return <span className={cls} aria-hidden="true">{name.trim().charAt(0).toUpperCase() || "?"}</span>;
}
