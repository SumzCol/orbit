/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

export type TInstanceUser = {
  id: string;
  email: string;
  first_name: string;
  last_name: string;
  display_name: string;
  avatar_url: string | undefined;
  date_joined: string;
  last_login_time: string | undefined;
  last_login_medium: string | undefined;
  is_active: boolean;
  /**
   * Whether this account has been explicitly deactivated, as opposed to merely
   * provisioned and never signed in. The server reads `is_active` together with
   * `last_logout_time` to tell those apart, so trust this over `is_active` alone.
   */
  is_deactivated: boolean;
  is_instance_admin: boolean;
  /**
   * Primary key of the InstanceAdmin row, or null for a regular member. Removing
   * admin access addresses that row, not the user, so it cannot be done without this.
   */
  instance_admin_id: string | null;
};
