"""Keep external FK metadata without managing Supabase's Auth table."""


def include_application_object(obj, name, type_, reflected, compare_to):
    # auth.users is a reference stub used by public.users' FK, not a table
    # Agrifos creates or alters. Do not suppress public tables, columns or FKs.
    return not (
        type_ == "table" and obj.schema == "auth" and name == "users"
    )
