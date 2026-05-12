import { AlertCircle } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { ApiError } from "@/lib/api/client";

function describe(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.body && typeof err.body === "object" && "detail" in err.body) {
      const detail = (err.body as { detail: unknown }).detail;
      if (typeof detail === "string") return detail;
    }
    return err.message;
  }
  if (err instanceof Error) return err.message;
  return "Unknown error";
}

export function ErrorState({
  title = "Something went wrong",
  error,
}: {
  title?: string;
  error: unknown;
}) {
  return (
    <Alert variant="destructive">
      <AlertCircle className="h-4 w-4" />
      <AlertTitle>{title}</AlertTitle>
      <AlertDescription>{describe(error)}</AlertDescription>
    </Alert>
  );
}
