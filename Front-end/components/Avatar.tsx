import { User } from "@/lib/api";

export function avatarUrl(user: User): string | null {
  return user.avatar_updated_at ? `/api/profile/avatar?v=${encodeURIComponent(user.avatar_updated_at)}` : null;
}

export function Avatar({ user, size = 36 }: { user: User; size?: number }) {
  const url = avatarUrl(user);
  const style = { width: size, height: size };
  if (url) {
    // eslint-disable-next-line @next/next/no-img-element
    return <img className="avatar" src={url} alt="" style={style} />;
  }
  return (
    <span className="avatar avatar-initial" style={{ ...style, fontSize: size * 0.42 }} aria-hidden="true">
      {user.name.trim().charAt(0).toUpperCase()}
    </span>
  );
}
