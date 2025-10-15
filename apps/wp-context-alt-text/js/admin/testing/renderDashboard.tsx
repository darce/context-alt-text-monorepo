import type { ReactElement, ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

interface CreateClientOptions {
    queryClient?: QueryClient;
}

type RenderDashboardOptions = CreateClientOptions &
    Parameters<typeof render>[1] & {
        withRouter?: boolean;
        routerEntries?: string[];
    };

type RenderDashboardResult = ReturnType<typeof render> & {
    queryClient: QueryClient;
    user: ReturnType<typeof userEvent.setup>;
};

const createQueryClient = (): QueryClient =>
    new QueryClient({
        defaultOptions: {
            queries: {
                retry: false,
                gcTime: 0,
            },
        },
    });

const Provider = ({
    children,
    client,
}: {
    children: ReactNode;
    client: QueryClient;
}): ReactElement => {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
};

export const renderDashboard = (
    ui: ReactElement,
    {
        queryClient: providedClient,
        withRouter = false,
        routerEntries = ["/"],
        ...options
    }: RenderDashboardOptions = {},
): RenderDashboardResult => {
    const queryClient = providedClient ?? createQueryClient();
    const user = userEvent.setup();

    const result = render(ui, {
        wrapper: ({ children }: { children: ReactNode }) => {
            const content = <Provider client={queryClient}>{children}</Provider>;

            if (!withRouter) {
                return content;
            }

            return <MemoryRouter initialEntries={routerEntries}>{content}</MemoryRouter>;
        },
        ...options,
    });

    return {
        ...result,
        queryClient,
        user,
    };
};

export const createTestQueryClient = createQueryClient;
