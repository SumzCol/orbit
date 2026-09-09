/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import React from "react";
// headless ui
import { Dialog, Transition } from "@headlessui/react";
// ui
import { Button } from "@makeplane/propel/components/button";

type Props = {
  isOpen: boolean;
  /** Shown so an administrator can see who they are about to suspend. */
  email: string;
  isSubmitting: boolean;
  handleClose: () => void;
  handleConfirm: () => void;
};

export function ConfirmDeactivateModal(props: Props) {
  const { isOpen, email, isSubmitting, handleClose, handleConfirm } = props;

  return (
    <Transition.Root show={isOpen} as={React.Fragment}>
      {/* Escape and a backdrop click are ignored while the request is in flight: closing
          then would hide a dialog whose outcome is still unknown, and the row it came
          from would go on showing the pre-deactivation state until the toast landed. */}
      <Dialog
        as="div"
        className="relative z-50"
        onClose={() => {
          if (!isSubmitting) handleClose();
        }}
      >
        <Transition.Child
          as={React.Fragment}
          enter="ease-out duration-300"
          enterFrom="opacity-0"
          enterTo="opacity-100"
          leave="ease-in duration-200"
          leaveFrom="opacity-100"
          leaveTo="opacity-0"
        >
          <div className="fixed inset-0 bg-backdrop transition-opacity" />
        </Transition.Child>
        <div className="fixed inset-0 z-10 overflow-y-auto">
          <div className="my-10 flex items-center justify-center p-4 text-center sm:p-0 md:my-32">
            <Transition.Child
              as={React.Fragment}
              enter="ease-out duration-300"
              enterFrom="opacity-0 translate-y-4 sm:translate-y-0 sm:scale-95"
              enterTo="opacity-100 translate-y-0 sm:scale-100"
              leave="ease-in duration-200"
              leaveFrom="opacity-100 translate-y-0 sm:scale-100"
              leaveTo="opacity-0 translate-y-4 sm:translate-y-0 sm:scale-95"
            >
              <Dialog.Panel className="relative transform overflow-hidden rounded-lg bg-surface-1 text-left shadow-raised-200 transition-all sm:my-8 sm:w-[30rem]">
                <div className="px-4 pt-5 pb-4 sm:p-6 sm:pb-4">
                  <Dialog.Title as="h3" className="text-16 leading-6 font-medium text-primary">
                    Deactivate {email}?
                  </Dialog.Title>
                  {/* Spelled out because "deactivate" understates it: the account is
                      signed out everywhere, its password is replaced, and it loses
                      every workspace and project it belonged to. */}
                  <div className="mt-3 flex flex-col gap-2 text-13 text-tertiary">
                    <p>They will not be able to sign in, and every session they have open ends immediately.</p>
                    <p>
                      Their workspace and project memberships are suspended and their password is reset. Pending
                      invitations to this address are withdrawn.
                    </p>
                    <p>
                      You can reactivate the account later, but that restores sign-in only — workspace access has to be
                      granted again by invitation.
                    </p>
                  </div>
                </div>
                <div className="flex items-center justify-end gap-2 p-4 sm:px-6">
                  <Button
                    variant="secondary"
                    size="md"
                    stretch="auto"
                    onClick={handleClose}
                    disabled={isSubmitting}
                    label="Cancel"
                  />
                  <Button
                    variant="danger"
                    size="md"
                    stretch="auto"
                    onClick={handleConfirm}
                    loading={isSubmitting}
                    label={isSubmitting ? "Deactivating" : "Deactivate"}
                  />
                </div>
              </Dialog.Panel>
            </Transition.Child>
          </div>
        </div>
      </Dialog>
    </Transition.Root>
  );
}
