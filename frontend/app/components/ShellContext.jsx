"use client";
// State bersama antara sidebar dan isi panel kanan. Riwayat & arsip hidup di
// SIDEBAR, padahal yang mengubahnya adalah halaman chat (buat percakapan baru,
// judul auto-generate, arsipkan). Context ini jembatannya.

import { createContext, useContext } from "react";

export const ShellContext = createContext({
  currentUser: null,
  chatHistory: [],
  archivedChats: [],
  refreshHistory: () => {},
  refreshArchived: () => {},
  activeTickets: [],
  refreshTickets: () => {},
});

export const useShell = () => useContext(ShellContext);
