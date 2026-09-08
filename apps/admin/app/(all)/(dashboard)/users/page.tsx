/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { observer } from "mobx-react";
import useSWR from "swr";
// icons
import { Search } from "lucide-react";
// plane internal packages
import { Button } from "@makeplane/propel/components/button";
import { Input, InputGroup } from "@makeplane/propel/components/input";
// components
import { PageWrapper } from "@/components/common/page-wrapper";
import { Skeleton } from "@/components/common/skeleton";
import { ConfirmDeactivateModal } from "@/components/users/confirm-deactivate-modal";
import { UserListItem } from "@/components/users/list-item";
import { setToast, TOAST_TYPE } from "@/providers/toast";
// hooks
import { useInstanceUser, useUser } from "@/hooks/store";
// types
import type { Route } from "./+types/page";

const UserManagementPage = observer(function UserManagementPage(_props: Route.ComponentProps) {
  // store
  const {
    users,
    userIds,
    loader,
    paginationInfo,
    search,
    setSearch,
    fetchUsers,
    fetchNextUsers,
    deactivateUser,
    activateUser,
    grantAdmin,
    revokeAdmin,
  } = useInstanceUser();
  const { currentUser } = useUser();
  // state — which row has an action in flight, and which is awaiting confirmation
  const [busyUserId, setBusyUserId] = useState<string | null>(null);
  const [pendingDeactivation, setPendingDeactivation] = useState<string | null>(null);

  useSWR("INSTANCE_USERS", () => fetchUsers());

  const hasNextPage = paginationInfo?.next_page_results && paginationInfo?.next_cursor !== undefined;

  const runAction = async (userId: string, action: () => Promise<void>, done: string) => {
    setBusyUserId(userId);
    try {
      await action();
      setToast({ type: TOAST_TYPE.SUCCESS, title: "Done", message: done });
    } catch (error) {
      // The server explains refusals precisely — sole admin of a workspace, instance
      // admin, and so on — so show that rather than a generic failure.
      const message = (error as { error?: string })?.error ?? "Something went wrong. Please try again.";
      setToast({ type: TOAST_TYPE.ERROR, title: "Could not complete", message });
    } finally {
      setBusyUserId(null);
    }
  };

  return (
    <PageWrapper
      customHeader={
        <div className="flex flex-col gap-1 border-b border-subtle pb-4">
          <h1 className="text-18 font-medium">Users</h1>
          <p className="text-13 text-tertiary">
            Everyone on this instance. Deactivating an account signs it out, suspends its workspace memberships and
            resets its password; reactivating restores sign-in only, so workspace access is granted again by invitation.
          </p>
        </div>
      }
    >
      <div className="flex flex-col gap-4">
        <InputGroup size="lg">
          <Search className="h-4 w-4 flex-shrink-0 text-tertiary" />
          <Input
            size="lg"
            type="text"
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              void fetchUsers(e.target.value);
            }}
            placeholder="Search by name or email"
          />
        </InputGroup>

        {loader === "init-loader" ? (
          <Skeleton className="space-y-3">
            <Skeleton.Item height="56px" />
            <Skeleton.Item height="56px" />
            <Skeleton.Item height="56px" />
          </Skeleton>
        ) : userIds.length === 0 ? (
          <p className="py-10 text-center text-13 text-tertiary">
            {search ? `No users match “${search}”.` : "No users yet."}
          </p>
        ) : (
          <div className="flex flex-col gap-2">
            {userIds.map((userId) => {
              const user = users[userId];
              if (!user) return null;
              return (
                <UserListItem
                  key={userId}
                  user={user}
                  isBusy={busyUserId === userId}
                  isSelf={currentUser?.id === userId}
                  onDeactivate={() => setPendingDeactivation(userId)}
                  onActivate={() =>
                    void runAction(userId, () => activateUser(userId), `${user.email} can sign in again.`)
                  }
                  onGrantAdmin={() =>
                    void runAction(userId, () => grantAdmin(userId), `${user.email} now has God Mode access.`)
                  }
                  onRevokeAdmin={() =>
                    void runAction(userId, () => revokeAdmin(userId), `${user.email} no longer has God Mode access.`)
                  }
                />
              );
            })}
          </div>
        )}

        {hasNextPage && (
          <Button
            variant="secondary"
            size="md"
            stretch="auto"
            onClick={() => void fetchNextUsers()}
            loading={loader === "pagination"}
            label="Load more"
          />
        )}
      </div>

      <ConfirmDeactivateModal
        isOpen={pendingDeactivation !== null}
        email={pendingDeactivation ? (users[pendingDeactivation]?.email ?? "") : ""}
        isSubmitting={busyUserId !== null && busyUserId === pendingDeactivation}
        handleClose={() => setPendingDeactivation(null)}
        handleConfirm={() => {
          const userId = pendingDeactivation;
          if (!userId) return;
          const email = users[userId]?.email ?? "";
          void runAction(userId, () => deactivateUser(userId), `${email} can no longer sign in.`).then(() =>
            setPendingDeactivation(null)
          );
        }}
      />
    </PageWrapper>
  );
});

export const meta: Route.MetaFunction = () => [{ title: "Users - God Mode" }];

export default UserManagementPage;
