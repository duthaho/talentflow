import { LogIn } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";

export default async function SignedOutPage({ searchParams }: PageProps<"/signed-out">) {
  const { error } = await searchParams;
  const message = typeof error === "string" ? error : undefined;
  return (
    <main className="flex flex-1 items-center justify-center p-6">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle role="heading" aria-level={1} className="text-xl">
            {message ? "Sign-in failed" : "You are signed out"}
          </CardTitle>
          <CardDescription>TalentFlow uses your organisation&apos;s Keycloak account.</CardDescription>
        </CardHeader>
        {message && (
          <div className="px-6">
            <Alert variant="destructive">
              <AlertTitle>We could not sign you in</AlertTitle>
              <AlertDescription>{message}</AlertDescription>
            </Alert>
          </div>
        )}
        <CardFooter>
          <Button asChild className="w-full">
            <a href="/auth/login">
              <LogIn aria-hidden />
              Sign in
            </a>
          </Button>
        </CardFooter>
      </Card>
    </main>
  );
}
