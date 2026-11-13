"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { ChangeEvent, FormEvent, useEffect, useRef, useState } from "react";
import { useAuth } from "@/components/AuthProvider";
import { Avatar } from "@/components/Avatar";
import { api, sendJson, User } from "@/lib/api";

const MAX_AVATAR_BYTES = 5 * 1024 * 1024;

function message(problem: unknown): string {
  return problem instanceof Error ? problem.message : "Something went wrong. Please try again.";
}

export default function ProfilePage() {
  const { user, loading, setUser } = useAuth();
  const router = useRouter();
  const fileInput = useRef<HTMLInputElement>(null);
  const loadedFor = useRef<number | null>(null);

  const [welcome, setWelcome] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState<string | null>(null);
  const [profileError, setProfileError] = useState<string | null>(null);

  const [avatarBusy, setAvatarBusy] = useState(false);
  const [avatarError, setAvatarError] = useState<string | null>(null);

  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [passwordBusy, setPasswordBusy] = useState(false);
  const [passwordError, setPasswordError] = useState<string | null>(null);

  useEffect(() => {
    if (!loading && !user) router.replace("/login");
    if (user && loadedFor.current !== user.id) {
      loadedFor.current = user.id;
      setName(user.name);
      setDescription(user.job_description);
    }
  }, [user, loading, router]);

  useEffect(() => {
    setWelcome(new URLSearchParams(window.location.search).has("welcome"));
  }, []);

  if (!user) return null;

  async function saveProfile(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setSaved(null);
    setProfileError(null);
    try {
      const changed = description.trim() !== user!.job_description;
      const updated = await sendJson<User>("/api/profile", "PUT", { name, job_description: description });
      setUser(updated);
      setName(updated.name);
      setDescription(updated.job_description);
      setSaved(
        changed && updated.job_description
          ? "Saved. We're checking the past 24 hours of jobs for you now, and new jobs will follow this description from today."
          : "Saved.",
      );
    } catch (problem) {
      setProfileError(message(problem));
    } finally {
      setSaving(false);
    }
  }

  async function chooseAvatar(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    setAvatarError(null);
    if (file.size > MAX_AVATAR_BYTES) {
      setAvatarError("Please choose an image under 5 MB.");
      return;
    }
    setAvatarBusy(true);
    try {
      const form = new FormData();
      form.append("file", file);
      setUser(await api<User>("/api/profile/avatar", { method: "PUT", body: form }));
    } catch (problem) {
      setAvatarError(message(problem));
    } finally {
      setAvatarBusy(false);
    }
  }

  async function removeAvatar() {
    setAvatarBusy(true);
    setAvatarError(null);
    try {
      setUser(await api<User>("/api/profile/avatar", { method: "DELETE" }));
    } catch (problem) {
      setAvatarError(message(problem));
    } finally {
      setAvatarBusy(false);
    }
  }

  async function changePassword(event: FormEvent) {
    event.preventDefault();
    setPasswordBusy(true);
    setPasswordError(null);
    try {
      await sendJson("/api/profile/password", "PUT", {
        current_password: currentPassword,
        new_password: newPassword,
      });
      // A full page load, because every session just ended, including this one.
      window.location.assign("/login?password-changed");
    } catch (problem) {
      setPasswordError(message(problem));
      setPasswordBusy(false);
    }
  }

  return (
    <main className="page profile">
      <h1>Your profile</h1>
      {welcome && !user.job_description && (
        <p className="notice" role="status">
          Welcome! Add your job description below to start getting jobs picked for you.
        </p>
      )}

      <section className="panel">
        <h2>Photo</h2>
        <div className="avatar-row">
          <Avatar user={user} size={88} />
          <div>
            <input ref={fileInput} type="file" hidden accept="image/jpeg,image/png,image/webp" onChange={chooseAvatar} />
            <div className="avatar-actions">
              <button type="button" className="button button-secondary" disabled={avatarBusy} onClick={() => fileInput.current?.click()}>
                {avatarBusy ? "Working…" : user.avatar_updated_at ? "Change photo" : "Upload photo"}
              </button>
              {user.avatar_updated_at && (
                <button type="button" className="button button-quiet" disabled={avatarBusy} onClick={removeAvatar}>Remove</button>
              )}
            </div>
            <p className="field-hint">JPG, PNG or WebP, up to 5 MB.</p>
            {avatarError && <p className="notice notice-error" role="alert">{avatarError}</p>}
          </div>
        </div>
      </section>

      <form className="panel" onSubmit={saveProfile}>
        <h2>What you&apos;re looking for</h2>
        <label htmlFor="description">Job description</label>
        <p className="field-hint" id="description-hint">
          Describe the jobs you want in your own words: the field, level, location, and anything to avoid. If you change
          this later, jobs already in your lists stay, and jobs from today onward follow the new description.
        </p>
        <textarea
          id="description"
          rows={5}
          maxLength={4000}
          aria-describedby="description-hint"
          placeholder="e.g. Software engineering and IT jobs in Addis Ababa or remote. Mid-level. No sales roles."
          value={description}
          onChange={(e) => {
            setDescription(e.target.value);
            setSaved(null);
          }}
        />
        <label htmlFor="name">Name</label>
        <input id="name" autoComplete="name" required maxLength={80} value={name} onChange={(e) => { setName(e.target.value); setSaved(null); }} />
        <label htmlFor="email">Email</label>
        <input id="email" value={user.email} readOnly disabled />
        {profileError && <p className="notice notice-error" role="alert">{profileError}</p>}
        {saved && <p className="notice" role="status">{saved} <Link href="/">See my jobs</Link></p>}
        <div className="form-actions">
          <button type="submit" className="button button-primary" disabled={saving}>{saving ? "Saving…" : "Save changes"}</button>
        </div>
      </form>

      <form className="panel" onSubmit={changePassword}>
        <h2>Change password</h2>
        <label htmlFor="current-password">Current password</label>
        <input id="current-password" type="password" autoComplete="current-password" required value={currentPassword} onChange={(e) => setCurrentPassword(e.target.value)} />
        <label htmlFor="new-password">New password</label>
        <input id="new-password" type="password" autoComplete="new-password" required minLength={8} maxLength={128} value={newPassword} onChange={(e) => setNewPassword(e.target.value)} />
        <p className="field-hint">At least 8 characters. You&apos;ll need to log in again on your devices.</p>
        {passwordError && <p className="notice notice-error" role="alert">{passwordError}</p>}
        <div className="form-actions">
          <button type="submit" className="button button-secondary" disabled={passwordBusy}>{passwordBusy ? "Changing…" : "Change password"}</button>
        </div>
      </form>
    </main>
  );
}
