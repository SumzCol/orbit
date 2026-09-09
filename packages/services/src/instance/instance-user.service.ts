/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { API_BASE_URL } from "@plane/constants";
import type { TInstanceUser, TPaginationInfo } from "@plane/types";
import { APIService } from "../api.service";

export type TInstanceUserPaginationInfo = TPaginationInfo & {
  results: TInstanceUser[];
};

/**
 * Instance-wide user administration, backing the God Mode user list.
 */
export class InstanceUserService extends APIService {
  constructor(BASE_URL?: string) {
    super(BASE_URL || API_BASE_URL);
  }

  async list(search?: string, nextPageCursor?: string): Promise<TInstanceUserPaginationInfo> {
    return this.get(`/api/instances/users/`, {
      params: { search: search || undefined, cursor: nextPageCursor },
    })
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }

  /**
   * Suspends the account. The server refuses when the target is an instance admin,
   * solely administers a project or workspace, or is the requester themselves.
   */
  async deactivate(userId: string): Promise<void> {
    return this.post(`/api/instances/users/${userId}/deactivate/`)
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }

  /**
   * Grants instance admin access. Addressed by email, which is what the existing
   * endpoint accepts.
   */
  async grantAdmin(email: string): Promise<void> {
    return this.post(`/api/instances/admins/`, { email, role: 20 })
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }

  /**
   * Removes instance admin access.
   *
   * Takes the InstanceAdmin row's id, not the user's — the endpoint deletes that
   * row. `instance_admin_id` on the listed user is exactly this value.
   */
  async revokeAdmin(instanceAdminId: string): Promise<void> {
    return this.delete(`/api/instances/admins/${instanceAdminId}/`)
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }

  /**
   * Restores the ability to sign in. Workspace access is not restored — it is
   * granted again by invitation.
   */
  async activate(userId: string): Promise<void> {
    return this.post(`/api/instances/users/${userId}/activate/`)
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }
}
