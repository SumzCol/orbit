/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
// plane internal packages
import { Button } from "@makeplane/propel/components/button";
import { Tooltip } from "@makeplane/propel/components/tooltip";
import { DeactivatedUserOutline } from "@makeplane/propel/icons";
import type { TInstanceUser } from "@plane/types";
import { cn, getFileURL, renderFormattedDate } from "@plane/utils";

type TUserListItemProps = {
  user: TInstanceUser;
  /** True while an action on this row is in flight. */
  isBusy: boolean;
  /** The signed-in administrator, who may not deactivate themselves. */
  isSelf: boolean;
  onDeactivate: () => void;
  onActivate: () => void;
  onGrantAdmin: () => void;
  onRevokeAdmin: () => void;
};

const fullName = (user: TInstanceUser) =>
  [user.first_name, user.last_name].filter(Boolean).join(" ") || user.display_name || user.email;

export const UserListItem = observer(function UserListItem(props: TUserListItemProps) {
  const { user, isBusy, isSelf, onDeactivate, onActivate, onGrantAdmin, onRevokeAdmin } = props;

  return (
    <div className="flex items-center justify-between gap-4 rounded-lg border border-subtle bg-layer-1 p-3">
      <div className="flex min-w-0 items-center gap-3">
        <span className="relative flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full bg-accent-primary text-11 text-on-color uppercase">
          {user.avatar_url ? (
            <img
              src={getFileURL(user.avatar_url)}
              className="absolute inset-0 h-full w-full rounded-full object-cover"
              alt=""
            />
          ) : (
            (fullName(user)[0] ?? "?")
          )}
        </span>

        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm truncate font-medium text-primary">{fullName(user)}</span>
            {user.is_instance_admin && (
              <span className="flex-shrink-0 rounded-sm border border-subtle px-1.5 py-0.5 text-11 text-tertiary">
                Admin
              </span>
            )}
            {user.is_deactivated && (
              <Tooltip label="This account cannot sign in">
                <span className="flex flex-shrink-0 items-center gap-1 rounded-sm border border-subtle px-1.5 py-0.5 text-11 text-tertiary">
                  <DeactivatedUserOutline className="h-3 w-3" />
                  Deactivated
                </span>
              </Tooltip>
            )}
          </div>
          <div className="truncate text-13 text-tertiary">{user.email}</div>
        </div>
      </div>

      <div className="flex flex-shrink-0 items-center gap-4">
        <div className="hidden text-right text-13 text-tertiary sm:block">
          <div>Joined {renderFormattedDate(user.date_joined)}</div>
          <div className={cn(user.last_login_time ? "" : "italic")}>
            {user.last_login_time ? `Last seen ${renderFormattedDate(user.last_login_time)}` : "Never signed in"}
          </div>
        </div>

        {/* Admin access is independent of whether the account is active, so this is
            offered either way. Revoking your own would drop you out of God Mode
            mid-session, so it is withheld for the signed-in administrator. */}
        {user.is_instance_admin ? (
          <Tooltip label={isSelf ? "You cannot remove your own admin access" : "Demote to a regular member"}>
            <span>
              <Button
                variant="secondary"
                size="sm"
                stretch="auto"
                onClick={onRevokeAdmin}
                loading={isBusy}
                disabled={isSelf}
                label="Remove admin"
              />
            </span>
          </Tooltip>
        ) : (
          <Tooltip label="Grant access to God Mode">
            <span>
              <Button
                variant="secondary"
                size="sm"
                stretch="auto"
                onClick={onGrantAdmin}
                loading={isBusy}
                disabled={user.is_deactivated}
                label="Make admin"
              />
            </span>
          </Tooltip>
        )}

        {user.is_deactivated ? (
          <Button variant="secondary" size="sm" stretch="auto" onClick={onActivate} loading={isBusy} label="Activate" />
        ) : (
          <Tooltip
            label={
              isSelf
                ? "You cannot deactivate your own account"
                : user.is_instance_admin
                  ? "Remove admin access before deactivating"
                  : "Suspend this account"
            }
          >
            {/* Wrapped: a disabled button does not emit the hover the tooltip needs. */}
            <span>
              <Button
                variant="danger"
                size="sm"
                stretch="auto"
                onClick={onDeactivate}
                loading={isBusy}
                disabled={isSelf || user.is_instance_admin}
                label="Deactivate"
              />
            </span>
          </Tooltip>
        )}
      </div>
    </div>
  );
});
