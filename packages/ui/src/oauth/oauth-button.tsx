/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import * as React from "react";
import { cn } from "../utils";

export interface OAuthButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  text: string;
  icon: React.ReactNode;
  compact?: boolean;
}

const OAuthButton = React.forwardRef(function OAuthButton(
  props: OAuthButtonProps,
  ref: React.ForwardedRef<HTMLButtonElement>
) {
  const { text, icon, compact = false, className = "", ...rest } = props;

  // Compact mode hides the label, which leaves the button with nothing but an icon:
  // no accessible name for assistive technology, and no way to tell providers apart
  // for anyone who does not recognise the mark. Supplying the label as `aria-label`
  // restores the name, and `title` gives sighted users a tooltip. Only applied when
  // compact -- with the label visible, `aria-label` would needlessly shadow it.
  const compactLabelProps = compact ? { title: text, "aria-label": text } : {};

  return (
    <button
      ref={ref}
      {...compactLabelProps}
      className={cn(
        "bg-onboarding-background-200 hover:bg-onboarding-background-300 flex h-9 w-full items-center justify-center gap-2 rounded-md border border-strong px-4 py-2.5 text-13 font-medium text-primary duration-300",
        className
      )}
      {...rest}
    >
      <div className="flex flex-shrink-0 items-center justify-center">{icon}</div>
      {!compact && (
        <span className="flex flex-grow items-center justify-center text-body-sm-regular transition-opacity duration-300">
          {text}
        </span>
      )}
    </button>
  );
});

OAuthButton.displayName = "plane-ui-oauth-button";

export { OAuthButton };
