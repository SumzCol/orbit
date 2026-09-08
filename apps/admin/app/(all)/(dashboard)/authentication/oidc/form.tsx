/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { isEmpty } from "lodash-es";
import Link from "next/link";
import { Controller, useForm } from "react-hook-form";
// plane internal packages
import { API_BASE_URL } from "@plane/constants";
import { Button } from "@makeplane/propel/components/button";
import { Switch } from "@makeplane/propel/components/switch";
import { TOAST_TYPE, setToast } from "@/providers/toast";
import type { IFormattedInstanceConfiguration, TInstanceOIDCAuthenticationConfigurationKeys } from "@plane/types";
// components
import { CodeBlock } from "@/components/common/code-block";
import { ConfirmDiscardModal } from "@/components/common/confirm-discard-modal";
import type { TControllerInputFormField } from "@/components/common/controller-input";
import type { TControllerSwitchFormField } from "@/components/common/controller-switch";
import { ControllerSwitch } from "@/components/common/controller-switch";
import { ControllerInput } from "@/components/common/controller-input";
import type { TCopyField } from "@/components/common/copy-field";
import { CopyField } from "@/components/common/copy-field";
// hooks
import { useInstance } from "@/hooks/store";

type Props = {
  config: IFormattedInstanceConfiguration;
};

type OIDCConfigFormValues = Record<TInstanceOIDCAuthenticationConfigurationKeys, string>;

const OIDC_FORM_SWITCH_FIELD: TControllerSwitchFormField<OIDCConfigFormValues> = {
  name: "ENABLE_OIDC_SYNC",
  label: "your identity provider",
};

export function InstanceOIDCConfigForm(props: Props) {
  const { config } = props;
  // states
  const [isDiscardChangesModalOpen, setIsDiscardChangesModalOpen] = useState(false);
  // store hooks
  const { updateInstanceConfigurations } = useInstance();
  // form data
  const {
    handleSubmit,
    control,
    reset,
    formState: { errors, isDirty, isSubmitting },
  } = useForm<OIDCConfigFormValues>({
    defaultValues: {
      OIDC_PROVIDER_NAME: config["OIDC_PROVIDER_NAME"] || "SSO",
      OIDC_ISSUER_URL: config["OIDC_ISSUER_URL"],
      OIDC_CLIENT_ID: config["OIDC_CLIENT_ID"],
      OIDC_CLIENT_SECRET: config["OIDC_CLIENT_SECRET"],
      ENABLE_OIDC_SYNC: config["ENABLE_OIDC_SYNC"] || "0",
      OIDC_ALLOW_UNVERIFIED_EMAIL: config["OIDC_ALLOW_UNVERIFIED_EMAIL"] || "0",
    },
  });

  const originURL = !isEmpty(API_BASE_URL) ? API_BASE_URL : typeof window !== "undefined" ? window.location.origin : "";

  const OIDC_FORM_FIELDS: TControllerInputFormField<OIDCConfigFormValues>[] = [
    {
      key: "OIDC_PROVIDER_NAME",
      type: "text",
      label: "Provider name",
      description: <>The name shown on the sign-in button, for example Okta, Entra ID, or Keycloak.</>,
      placeholder: "SSO",
      error: Boolean(errors.OIDC_PROVIDER_NAME),
      required: false,
    },
    {
      key: "OIDC_ISSUER_URL",
      type: "text",
      label: "Issuer URL",
      description: (
        <>
          Your provider&apos;s issuer identifier. Plane reads every endpoint it needs from{" "}
          <CodeBlock>{"<issuer>/.well-known/openid-configuration"}</CodeBlock>, so this must be an{" "}
          <CodeBlock>https</CodeBlock> URL and must match the <CodeBlock>iss</CodeBlock> claim your provider issues.
        </>
      ),
      placeholder: "https://your-org.okta.com",
      error: Boolean(errors.OIDC_ISSUER_URL),
      required: true,
    },
    {
      key: "OIDC_CLIENT_ID",
      type: "text",
      label: "Client ID",
      description: <>The client ID of the application you registered with your identity provider.</>,
      placeholder: "0oa1b2c3d4e5f6g7h8i9",
      error: Boolean(errors.OIDC_CLIENT_ID),
      required: true,
    },
    {
      key: "OIDC_CLIENT_SECRET",
      type: "password",
      label: "Client secret",
      description: <>The client secret issued alongside the client ID.</>,
      placeholder: "*****************************",
      error: Boolean(errors.OIDC_CLIENT_SECRET),
      required: true,
    },
  ];

  const OIDC_SERVICE_FIELD: TCopyField[] = [
    {
      key: "Callback_URL",
      label: "Callback URL",
      url: `${originURL}/auth/oidc/callback/`,
      description: (
        <>
          We will auto-generate this. Paste it into the <CodeBlock darkerShade>Redirect URI</CodeBlock> (also called
          sign-in redirect URI) field of the application you registered with your identity provider.
        </>
      ),
    },
    {
      key: "Spaces_Callback_URL",
      label: "Callback URL for Spaces",
      url: `${originURL}/auth/spaces/oidc/callback/`,
      description: (
        <>
          Add this as a second <CodeBlock darkerShade>Redirect URI</CodeBlock> on the same application. Signing in to
          published Spaces comes back here instead, and providers reject any redirect URI they have not been given.
        </>
      ),
    },
  ];

  const onSubmit = async (formData: OIDCConfigFormValues) => {
    const payload: Partial<OIDCConfigFormValues> = { ...formData };

    try {
      const response = await updateInstanceConfigurations(payload);
      setToast({
        type: TOAST_TYPE.SUCCESS,
        title: "Done!",
        message: "Your OIDC authentication is configured. You should test it now.",
      });
      reset({
        OIDC_PROVIDER_NAME: response.find((item) => item.key === "OIDC_PROVIDER_NAME")?.value,
        OIDC_ISSUER_URL: response.find((item) => item.key === "OIDC_ISSUER_URL")?.value,
        OIDC_CLIENT_ID: response.find((item) => item.key === "OIDC_CLIENT_ID")?.value,
        OIDC_CLIENT_SECRET: response.find((item) => item.key === "OIDC_CLIENT_SECRET")?.value,
        ENABLE_OIDC_SYNC: response.find((item) => item.key === "ENABLE_OIDC_SYNC")?.value,
        OIDC_ALLOW_UNVERIFIED_EMAIL: response.find((item) => item.key === "OIDC_ALLOW_UNVERIFIED_EMAIL")?.value,
      });
    } catch (err) {
      console.error(err);
    }
  };

  const handleGoBack = (e: React.MouseEvent<HTMLAnchorElement, MouseEvent>) => {
    if (isDirty) {
      e.preventDefault();
      setIsDiscardChangesModalOpen(true);
    }
  };

  return (
    <>
      <ConfirmDiscardModal
        isOpen={isDiscardChangesModalOpen}
        onDiscardHref="/authentication"
        handleClose={() => setIsDiscardChangesModalOpen(false)}
      />
      <div className="flex flex-col gap-8">
        <div className="grid w-full grid-cols-2 gap-x-12 gap-y-8">
          <div className="col-span-2 flex flex-col gap-y-4 pt-1 md:col-span-1">
            <div className="pt-2.5 text-18 font-medium">Provider-provided details for Plane</div>
            {OIDC_FORM_FIELDS.map((field) => (
              <ControllerInput
                key={field.key}
                control={control}
                type={field.type}
                name={field.key}
                label={field.label}
                description={field.description}
                placeholder={field.placeholder}
                error={field.error}
                required={field.required}
              />
            ))}
            <ControllerSwitch control={control} field={OIDC_FORM_SWITCH_FIELD} />

            {/* Kept separate from the sync switch: this one relaxes a security check,
                so it needs to say plainly what turning it on means. */}
            <div className="border-custom-border-200 flex items-start justify-between gap-4 border-t pt-4">
              <div className="flex flex-col gap-1">
                <h4 className="text-sm text-custom-text-300">Accept accounts your provider has not verified</h4>
                <p className="text-xs text-custom-text-400">
                  Plane matches accounts by email address. Leave this off unless your provider never sends an{" "}
                  <CodeBlock>email_verified</CodeBlock> claim (Entra ID commonly omits it). Turning it on means trusting
                  your provider to only ever assert addresses it controls.
                </p>
              </div>
              <div className="relative shrink-0 pt-1">
                <Controller
                  control={control}
                  name="OIDC_ALLOW_UNVERIFIED_EMAIL"
                  render={({ field: { value, onChange } }) => {
                    const isOn = value === "1";
                    return <Switch checked={isOn} onCheckedChange={() => onChange(isOn ? "0" : "1")} size="sm" />;
                  }}
                />
              </div>
            </div>

            <div className="flex flex-col gap-1 pt-4">
              <div className="flex items-center gap-4">
                <Button
                  variant="primary"
                  size="md"
                  stretch="auto"
                  onClick={(e) => void handleSubmit(onSubmit)(e)}
                  loading={isSubmitting}
                  disabled={!isDirty}
                  label={isSubmitting ? "Saving" : "Save changes"}
                />
                <Button
                  variant="secondary"
                  size="md"
                  stretch="auto"
                  nativeButton={false}
                  render={<Link href="/authentication" onClick={handleGoBack} />}
                  label="Go back"
                />
              </div>
            </div>
          </div>
          <div className="col-span-2 md:col-span-1">
            <div className="flex flex-col gap-y-4 rounded-lg bg-layer-3 px-6 pt-1.5 pb-4">
              <div className="pt-2 text-18 font-medium">Plane-provided details for your provider</div>
              {OIDC_SERVICE_FIELD.map((field) => (
                <CopyField key={field.key} label={field.label} url={field.url} description={field.description} />
              ))}
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
