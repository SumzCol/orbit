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
  grantAdmin: (userId: string) => Promise<void>;
  revokeAdmin: (userId: string) => Promise<void>;
  activateUser: (userId: string) => Promise<void>;
}

export class InstanceUserStore implements IInstanceUserStore {
  // observables
  loader: TLoader = "init-loader";
  users: Record<string, TInstanceUser> = {};
  paginationInfo: TPaginationInfo | undefined = undefined;
  search = "";
  /** Sequence number of the most recent list request. Deliberately not observable --
   *  it is bookkeeping, and nothing renders from it. */
  private latestListRequest = 0;
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
      grantAdmin: action,
      revokeAdmin: action,
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
    // Typing fires one request per keystroke, on top of the initial fetch, and they can
    // land out of order. Without this an older, slower response would overwrite the list
    // with results for a term the person has already typed past.
    const requestId = ++this.latestListRequest;
    try {
      this.loader = this.userIds.length > 0 ? "mutation" : "init-loader";
      const page = await this.instanceUserService.list(search ?? this.search);
      if (requestId !== this.latestListRequest) return page.results;
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
      // Only the newest request owns the loader; an outdated one clearing it would
      // hide the spinner while the current request is still running.
      if (requestId === this.latestListRequest) this.loader = "loaded";
    }
  };

  fetchNextUsers = async (): Promise<TInstanceUser[] | undefined> => {
    if (!this.paginationInfo?.next_page_results || this.paginationInfo?.next_cursor === undefined) return undefined;
    // Counted alongside fetchUsers: a page that arrives after the search has moved on
    // belongs to the previous result set, and merging it would put back rows that no
    // longer match. Read outside the try so the finally can see it too.
    const requestId = ++this.latestListRequest;
    const cursor = this.paginationInfo.next_cursor;
    try {
      this.loader = "pagination";
      const page = await this.instanceUserService.list(this.search, cursor);
      if (requestId !== this.latestListRequest) return page.results;
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
      if (requestId === this.latestListRequest) this.loader = "loaded";
    }
  };

  deactivateUser = async (userId: string): Promise<void> => {
    await this.instanceUserService.deactivate(userId);
    // Refetched rather than patched locally: deactivation also suspends memberships
    // and drops sessions, and the row should reflect what the server now holds.
    await this.fetchUsers();
  };

  grantAdmin = async (userId: string): Promise<void> => {
    const user = this.users[userId];
    if (!user) return;
    await this.instanceUserService.grantAdmin(user.email);
    await this.fetchUsers();
  };

  revokeAdmin = async (userId: string): Promise<void> => {
    // The endpoint deletes the InstanceAdmin row, so it is addressed by that row's
    // id rather than the user's. The list carries it for exactly this call.
    const instanceAdminId = this.users[userId]?.instance_admin_id;
    if (!instanceAdminId) return;
    await this.instanceUserService.revokeAdmin(instanceAdminId);
    await this.fetchUsers();
  };

  activateUser = async (userId: string): Promise<void> => {
    await this.instanceUserService.activate(userId);
    await this.fetchUsers();
  };
}
