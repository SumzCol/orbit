/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { observer } from "mobx-react";
import useSWR from "swr";
// icons
import { ShieldCheck } from "lucide-react";
// plane internal packages
import { Switch } from "@makeplane/propel/components/switch";
// components
import { AuthenticationMethodCard } from "@/components/authentication/authentication-method-card";
import { PageWrapper } from "@/components/common/page-wrapper";
import { Skeleton } from "@/components/common/skeleton";
import { setPromiseToast } from "@/providers/toast";
// hooks
import { useInstance } from "@/hooks/store";
// types
import type { Route } from "./+types/page";
// local
import { InstanceOIDCConfigForm } from "./form";

const InstanceOIDCAuthenticationPage = observer(function InstanceOIDCAuthenticationPage(_props: Route.ComponentProps) {
  // store
  const { fetchInstanceConfigurations, formattedConfig, updateInstanceConfigurations } = useInstance();
  // state
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);
  // config
  const enableOIDCConfig = formattedConfig?.IS_OIDC_ENABLED ?? "";
  const isEnabled = Boolean(parseInt(enableOIDCConfig));
  // Every endpoint is discovered from the issuer, so without it plus the client
  // credentials the method cannot work at all.
  const isOIDCConfigured =
    !!formattedConfig?.OIDC_ISSUER_URL && !!formattedConfig?.OIDC_CLIENT_ID && !!formattedConfig?.OIDC_CLIENT_SECRET;
  // Block turning it *on* before it is configured, which would leave the instance
  // advertising a sign-in button that can only fail. Turning it off stays available
  // whatever the config says — otherwise clearing a field would strand the method
  // enabled with no way back.
  const cannotEnableYet = !isOIDCConfigured && !isEnabled;

  useSWR("INSTANCE_CONFIGURATIONS", () => fetchInstanceConfigurations());

  const updateConfig = async (key: "IS_OIDC_ENABLED", value: string) => {
    setIsSubmitting(true);

    const payload = {
      [key]: value,
    };

    const updateConfigPromise = updateInstanceConfigurations(payload);

    setPromiseToast(updateConfigPromise, {
      loading: "Saving Configuration",
      success: {
        title: "Configuration saved",
        message: () => `OIDC authentication is now ${value === "1" ? "active" : "disabled"}.`,
      },
      error: {
        title: "Error",
        message: () => "Failed to save configuration",
      },
    });

    // try/finally rather than the .then/.catch pair the sibling provider pages use:
    // that shape trips oxlint's promise(always-return), which lint-staged runs with
    // --deny-warnings, and this reads better anyway — one place resets the flag.
    try {
      await updateConfigPromise;
    } catch (err) {
      console.error(err);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <PageWrapper
      customHeader={
        <AuthenticationMethodCard
          name="OIDC"
          description="Allow members to log in or sign up to Plane through any OpenID Connect identity provider."
          icon={<ShieldCheck className="h-6 w-6 p-0.5 text-tertiary" />}
          config={
            <span title={cannotEnableYet ? "Add the issuer URL, client ID and client secret first." : undefined}>
              <Switch
                checked={isEnabled}
                onCheckedChange={() => {
                  updateConfig("IS_OIDC_ENABLED", isEnabled ? "0" : "1");
                }}
                size="sm"
                disabled={isSubmitting || !formattedConfig || cannotEnableYet}
              />
            </span>
          }
          disabled={isSubmitting || !formattedConfig}
          withBorder={false}
        />
      }
    >
      {formattedConfig ? (
        <InstanceOIDCConfigForm config={formattedConfig} />
      ) : (
        <Skeleton className="space-y-8">
          <Skeleton.Item height="50px" width="25%" />
          <Skeleton.Item height="50px" />
          <Skeleton.Item height="50px" />
          <Skeleton.Item height="50px" />
          <Skeleton.Item height="50px" width="50%" />
        </Skeleton>
      )}
    </PageWrapper>
  );
});

export const meta: Route.MetaFunction = () => [{ title: "OIDC Authentication - God Mode" }];

export default InstanceOIDCAuthenticationPage;
