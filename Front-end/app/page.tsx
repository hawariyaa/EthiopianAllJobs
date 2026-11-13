"use client";

import { useAuth } from "@/components/AuthProvider";
import { Feed } from "@/components/Feed";
import { Landing } from "@/components/Landing";

export default function Home() {
  const { user, loading } = useAuth();
  if (loading) return null;
  return user ? <Feed /> : <Landing />;
}
