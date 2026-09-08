/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { set } from "lodash-es";
import { action, computed, makeObservable, observable, runInAction } from "mobx";
// plane imports
import { InstanceUserService } from "@plane/services";
import type { TInstanceUser, TLoader, TPaginationInfo } from "@plane/types";
// local imports
import type { RootStore } from "@/store/root.store";

export interface IInstanceUserStore {
  // observables
  loader: TLoader;
  users: Record<string, TInstanceUser>;
  paginationInfo: TPaginationInfo | undefined;
  search: string;
  // computed
  userIds: string[];
  // actions
  setSearch: (search: string) => void;
  fetchUsers: (search?: string) => Promise<TInstanceUser[]>;
  fetchNextUsers: () => Promise<TInstanceUser[] | undefined>;
  deactivateUser: (userId: string) => Promise<void>;
  activateUser: (userId: string) => Promise<void>;
}

export class InstanceUserStore implements IInstanceUserStore {
  // observables
  loader: TLoader = "init-loader";
  users: Record<string, TInstanceUser> = {};
  paginationInfo: TPaginationInfo | undefined = undefined;
  search = "";
  // services
  instanceUserService;

  constructor(private store: RootStore) {
    makeObservable(this, {
      loader: observable,
      users: observable,
      paginationInfo: observable,
      search: observable.ref,
      userIds: computed,
      setSearch: action,
      fetchUsers: action,
      fetchNextUsers: action,
      deactivateUser: action,
      activateUser: action,
    });
    this.instanceUserService = new InstanceUserService();
  }

  /** Newest first, matching the order the endpoint returns. */
  get userIds() {
    return Object.keys(this.users);
  }

  setSearch = (search: string) => {
    this.search = search;
  };

  fetchUsers = async (search?: string): Promise<TInstanceUser[]> => {
    try {
      this.loader = this.userIds.length > 0 ? "mutation" : "init-loader";
      const page = await this.instanceUserService.list(search ?? this.search);
      runInAction(() => {
        const { results, ...paginationInfo } = page;
        // Replaced rather than merged: a search returns a different set, and keeping
        // the previous one would leave rows on screen that no longer match.
        this.users = {};
        results.forEach((user) => set(this.users, [user.id], user));
        set(this, "paginationInfo", paginationInfo);
      });
      return page.results;
    } catch (error) {
      console.error("Error fetching instance users", error);
      throw error;
    } finally {
      this.loader = "loaded";
    }
  };

  fetchNextUsers = async (): Promise<TInstanceUser[] | undefined> => {
    try {
      if (!this.paginationInfo?.next_page_results || this.paginationInfo?.next_cursor === undefined) return undefined;
      this.loader = "pagination";
      const page = await this.instanceUserService.list(this.search, this.paginationInfo.next_cursor);
      runInAction(() => {
        const { results, ...paginationInfo } = page;
        results.forEach((user) => set(this.users, [user.id], user));
        set(this, "paginationInfo", paginationInfo);
      });
      return page.results;
    } catch (error) {
      console.error("Error fetching more instance users", error);
      throw error;
    } finally {
      this.loader = "loaded";
    }
  };

  deactivateUser = async (userId: string): Promise<void> => {
    await this.instanceUserService.deactivate(userId);
    // Refetched rather than patched locally: deactivation also suspends memberships
    // and drops sessions, and the row should reflect what the server now holds.
    await this.fetchUsers();
  };

  activateUser = async (userId: string): Promise<void> => {
    await this.instanceUserService.activate(userId);
    await this.fetchUsers();
  };
}
