/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

// icons
import { ShieldCheck } from "lucide-react";
// plane imports
import { useSearchParams } from "next/navigation";
import { useTheme } from "next-themes";
import { API_BASE_URL } from "@plane/constants";
import type { TOAuthConfigs, TOAuthOption } from "@plane/types";
// assets
import giteaLogo from "@/app/assets/logos/gitea-logo.svg?url";
import githubLightLogo from "@/app/assets/logos/github-black.png?url";
import githubDarkLogo from "@/app/assets/logos/github-dark.svg?url";
import gitlabLogo from "@/app/assets/logos/gitlab-logo.svg?url";
import googleLogo from "@/app/assets/logos/google-logo.svg?url";
// hooks
import { useInstance } from "@/hooks/store/use-instance";

export const useCoreOAuthConfig = (oauthActionText: string): TOAuthConfigs => {
  //router
  const searchParams = useSearchParams();
  // query params
  const next_path = searchParams.get("next_path");
  // theme
  const { resolvedTheme } = useTheme();
  // store hooks
  const { config } = useInstance();
  // derived values
  const isOAuthEnabled =
    (config &&
      (config?.is_google_enabled ||
        config?.is_github_enabled ||
        config?.is_gitlab_enabled ||
        config?.is_gitea_enabled ||
        config?.is_oidc_enabled)) ||
    false;
  const oAuthOptions: TOAuthOption[] = [
    {
      id: "google",
      text: `${oauthActionText} with Google`,
      icon: <img src={googleLogo} height={18} width={18} alt="Google Logo" />,
      onClick: () => {
        window.location.assign(
          `${API_BASE_URL}/auth/google/${next_path ? `?next_path=${encodeURIComponent(next_path)}` : ``}`
        );
      },
      enabled: config?.is_google_enabled,
    },
    {
      id: "github",
      text: `${oauthActionText} with GitHub`,
      icon: (
        <img
          src={resolvedTheme === "dark" ? githubLightLogo : githubDarkLogo}
          height={18}
          width={18}
          alt="GitHub Logo"
        />
      ),
      onClick: () => {
        window.location.assign(
          `${API_BASE_URL}/auth/github/${next_path ? `?next_path=${encodeURIComponent(next_path)}` : ``}`
        );
      },
      enabled: config?.is_github_enabled,
    },
    {
      id: "gitlab",
      text: `${oauthActionText} with GitLab`,
      icon: <img src={gitlabLogo} height={18} width={18} alt="GitLab Logo" />,
      onClick: () => {
        window.location.assign(
          `${API_BASE_URL}/auth/gitlab/${next_path ? `?next_path=${encodeURIComponent(next_path)}` : ``}`
        );
      },
      enabled: config?.is_gitlab_enabled,
    },
    {
      id: "gitea",
      text: `${oauthActionText} with Gitea`,
      icon: <img src={giteaLogo} height={18} width={18} alt="Gitea Logo" />,
      onClick: () => {
        window.location.assign(
          `${API_BASE_URL}/auth/gitea/${next_path ? `?next_path=${encodeURIComponent(next_path)}` : ``}`
        );
      },
      enabled: config?.is_gitea_enabled,
    },
    {
      id: "oidc",
      // The provider is generic, so the button carries whatever the instance admin
      // named their IdP rather than a hardcoded vendor.
      text: `${oauthActionText} with ${config?.oidc_provider_name || "SSO"}`,
      icon: <ShieldCheck className="h-[18px] w-[18px] text-tertiary" />,
      onClick: () => {
        // Encoded, unlike the providers above: useSearchParams() hands back a decoded
        // value, so a next_path containing ? & or # would otherwise split into extra
        // query parameters. The server decodes it again before validating.
        // The Spaces endpoints, unlike the providers above which all point at the
        // /app ones. Those log the user in with is_app=True and land them on the web
        // app rather than back on Spaces; /auth/spaces/oidc/ uses the Spaces session
        // keys, its own callback, and returns to SPACE_BASE_URL.
        window.location.assign(
          `${API_BASE_URL}/auth/spaces/oidc/${next_path ? `?next_path=${encodeURIComponent(next_path)}` : ``}`
        );
      },
      enabled: config?.is_oidc_enabled,
    },
  ];

  return {
    isOAuthEnabled,
    oAuthOptions,
  };
};
