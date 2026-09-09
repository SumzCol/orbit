/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
// icons
import { TriangleAlert } from "lucide-react";
// plane internal packages
import { LOGIN_MEDIUM_LABELS } from "@plane/constants";
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

/* God Mode authenticates by password alone — InstanceAdminSignInEndpoint calls
   check_password and has no provider branch — so an account provisioned through OIDC
   or any other provider holds a random password it can never know. Granting it admin
   access is real but not sufficient, and the gap is invisible until someone is locked
   out, so both the badge and the promote tooltip name it. */
const NO_PASSWORD_EXPLANATION =
  "God Mode signs in with an email and password only. This account was created through an identity provider and has no password, so it must set one from its profile in the main app before it can sign in here.";

const fullName = (user: TInstanceUser) =>
  [user.first_name, user.last_name].filter(Boolean).join(" ") || user.display_name || user.email;

/** How this account last signed in, named the way the workspace members screen names it.
 *  Falls back to the raw value so a provider added to the API but not yet to the label
 *  map shows something true rather than "undefined". */
const signInMethod = (user: TInstanceUser) =>
  LOGIN_MEDIUM_LABELS[user.last_login_medium as keyof typeof LOGIN_MEDIUM_LABELS] ?? user.last_login_medium;

const PILL = "flex flex-shrink-0 items-center gap-1 rounded-sm border px-1.5 py-0.5 text-11";

function Avatar({ user }: { user: TInstanceUser }) {
  return (
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
  );
}

/** What this account is, and anything about it that needs explaining. */
function Badges({ user }: { user: TInstanceUser }) {
  return (
    <>
      {user.is_instance_admin && <span className={cn(PILL, "border-subtle text-tertiary")}>Admin</span>}
      {user.is_instance_admin && user.is_password_autoset && (
        <Tooltip label={NO_PASSWORD_EXPLANATION}>
          <span className={cn(PILL, "border-warning-subtle bg-warning-subtle text-warning-primary")}>
            <TriangleAlert className="h-3 w-3" />
            No password
          </span>
        </Tooltip>
      )}
      {user.is_deactivated && (
        <Tooltip label="This account cannot sign in">
          <span className={cn(PILL, "border-subtle text-tertiary")}>
            <DeactivatedUserOutline className="h-3 w-3" />
            Deactivated
          </span>
        </Tooltip>
      )}
    </>
  );
}

/* Every action below is wrapped in a span: a disabled button emits no hover, so the
   tooltip explaining why it is disabled would never appear without one. */

/** Grant or remove God Mode access.
 *
 *  Removing it is offered whether or not the account is active -- stripping access from
 *  a suspended account is exactly when you want it -- but withheld for the signed-in
 *  administrator, whose own revocation would drop them out of God Mode mid-session.
 *
 *  Granting it to a deactivated account is refused. The server allows it, and nothing
 *  deadlocks if it happens, but the grant would be inert: the account cannot sign in at
 *  all, so it cannot reach God Mode, and the row would read Admin and Deactivated at
 *  once. Activating first makes the grant mean something. */
function AdminAccessAction(props: {
  user: TInstanceUser;
  isBusy: boolean;
  isSelf: boolean;
  onGrantAdmin: () => void;
  onRevokeAdmin: () => void;
}) {
  const { user, isBusy, isSelf, onGrantAdmin, onRevokeAdmin } = props;

  if (user.is_instance_admin)
    return (
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
    );

  // One value drives both the tooltip and `disabled`, so a refused action always
  // explains itself -- a greyed button whose tooltip reads like an invitation is worse
  // than no tooltip.
  const refusal = user.is_deactivated ? "Activate this account before granting God Mode access" : undefined;

  return (
    <Tooltip
      label={
        refusal ??
        (user.is_password_autoset ? `Grant access to God Mode. ${NO_PASSWORD_EXPLANATION}` : "Grant access to God Mode")
      }
    >
      <span>
        <Button
          variant="secondary"
          size="sm"
          stretch="auto"
          onClick={onGrantAdmin}
          loading={isBusy}
          disabled={refusal !== undefined}
          label="Make admin"
        />
      </span>
    </Tooltip>
  );
}

/** Suspend or restore sign-in. An instance admin must be demoted first, so that
 *  losing an administrator is always a deliberate second step. */
function AccountStateAction(props: {
  user: TInstanceUser;
  isBusy: boolean;
  isSelf: boolean;
  onDeactivate: () => void;
  onActivate: () => void;
}) {
  const { user, isBusy, isSelf, onDeactivate, onActivate } = props;

  if (user.is_deactivated)
    return (
      <Button variant="secondary" size="sm" stretch="auto" onClick={onActivate} loading={isBusy} label="Activate" />
    );

  const refusal = isSelf
    ? "You cannot deactivate your own account"
    : user.is_instance_admin
      ? "Remove admin access before deactivating"
      : undefined;

  return (
    <Tooltip label={refusal ?? "Suspend this account"}>
      <span>
        <Button
          variant="danger"
          size="sm"
          stretch="auto"
          onClick={onDeactivate}
          loading={isBusy}
          disabled={refusal !== undefined}
          label="Deactivate"
        />
      </span>
    </Tooltip>
  );
}

export const UserListItem = observer(function UserListItem(props: TUserListItemProps) {
  const { user, isBusy, isSelf, onDeactivate, onActivate, onGrantAdmin, onRevokeAdmin } = props;

  return (
    <div className="flex items-center justify-between gap-4 rounded-lg border border-subtle bg-layer-1 p-3">
      <div className="flex min-w-0 items-center gap-3">
        <Avatar user={user} />
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm truncate font-medium text-primary">{fullName(user)}</span>
            <Badges user={user} />
          </div>
          <div className="truncate text-13 text-tertiary">{user.email}</div>
        </div>
      </div>

      <div className="flex flex-shrink-0 items-center gap-4">
        <div className="hidden text-right text-13 text-tertiary sm:block">
          <div>Joined {renderFormattedDate(user.date_joined)}</div>
          {/* The method is only shown next to a real sign-in. last_login_medium is a
              non-nullable column defaulting to "email", so on an account that has never
              signed in it is a default rather than a fact, and printing it would invent
              a history. It is also the *last* method, not the one the account was made
              with -- Plane records no such thing -- hence "via" rather than "created". */}
          <div className={cn(user.last_login_time ? "" : "italic")}>
            {user.last_login_time
              ? `Last seen ${renderFormattedDate(user.last_login_time)} via ${signInMethod(user)}`
              : "Never signed in"}
          </div>
        </div>

        <AdminAccessAction
          user={user}
          isBusy={isBusy}
          isSelf={isSelf}
          onGrantAdmin={onGrantAdmin}
          onRevokeAdmin={onRevokeAdmin}
        />
        <AccountStateAction
          user={user}
          isBusy={isBusy}
          isSelf={isSelf}
          onDeactivate={onDeactivate}
          onActivate={onActivate}
        />
      </div>
    </div>
  );
});
