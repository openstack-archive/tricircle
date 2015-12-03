# Devstack extras script to install Tricircle

# Test if any tricircle services are enabled
# is_tricircle_enabled
function is_tricircle_enabled {
    [[ ,${ENABLED_SERVICES} =~ ,"t-" ]] && return 0
    return 1
}

# create_tricircle_accounts() - Set up common required tricircle
# service accounts in keystone
# Project               User            Roles
# -------------------------------------------------------------------------
# $SERVICE_TENANT_NAME  tricircle       service

function create_tricircle_accounts {
    if [[ "$ENABLED_SERVICES" =~ "t-api" ]]; then
        create_service_user "tricircle"

        if [[ "$KEYSTONE_CATALOG_BACKEND" = 'sql' ]]; then
            local tricircle_api=$(get_or_create_service "tricircle" \
                "Cascading" "OpenStack Cascading Service")
            get_or_create_endpoint $tricircle_api \
                "$REGION_NAME" \
                "$SERVICE_PROTOCOL://$TRICIRCLE_API_HOST:$TRICIRCLE_API_PORT/v1.0" \
                "$SERVICE_PROTOCOL://$TRICIRCLE_API_HOST:$TRICIRCLE_API_PORT/v1.0" \
                "$SERVICE_PROTOCOL://$TRICIRCLE_API_HOST:$TRICIRCLE_API_PORT/v1.0"
        fi
    fi
}

# create_tricircle_cache_dir() - Set up cache dir for tricircle
function create_tricircle_cache_dir {

    # Delete existing dir
    sudo rm -rf $TRICIRCLE_AUTH_CACHE_DIR
    sudo mkdir -p $TRICIRCLE_AUTH_CACHE_DIR
    sudo chown `whoami` $TRICIRCLE_AUTH_CACHE_DIR

}

function configure_tricircle_api {
    if is_service_enabled t-api ; then
        echo "Configuring Tricircle API"

        touch $TRICIRCLE_API_CONF
        iniset $TRICIRCLE_API_CONF DEFAULT debug $ENABLE_DEBUG_LOG_LEVEL
        iniset $TRICIRCLE_API_CONF DEFAULT verbose True
        iniset $TRICIRCLE_API_CONF DEFAULT use_syslog $SYSLOG
        iniset $TRICIRCLE_API_CONF database connection `database_connection_url tricircle`

        iniset $TRICIRCLE_API_CONF client admin_username admin
        iniset $TRICIRCLE_API_CONF client admin_password $ADMIN_PASSWORD
        iniset $TRICIRCLE_API_CONF client admin_tenant demo
        iniset $TRICIRCLE_API_CONF client auto_refresh_endpoint True
        iniset $TRICIRCLE_API_CONF client top_site_name $OS_REGION_NAME

        iniset $TRICIRCLE_API_CONF oslo_concurrency lock_path $TRICIRCLE_STATE_PATH/lock

        setup_colorized_logging $TRICIRCLE_API_CONF DEFAULT tenant_name

        if is_service_enabled keystone; then

            create_tricircle_cache_dir

            # Configure auth token middleware
            configure_auth_token_middleware $TRICIRCLE_API_CONF tricircle \
                $TRICIRCLE_AUTH_CACHE_DIR

        else
            iniset $TRICIRCLE_API_CONF DEFAULT auth_strategy noauth
        fi

    fi
}


if [[ "$Q_ENABLE_TRICIRCLE" == "True" ]]; then
    if [[ "$1" == "stack" && "$2" == "pre-install" ]]; then
        echo summary "Tricircle pre-install"
    elif [[ "$1" == "stack" && "$2" == "install" ]]; then
        echo_summary "Installing Tricircle"

        git_clone $TRICIRCLE_REPO $TRICIRCLE_DIR $TRICIRCLE_BRANCH


    elif [[ "$1" == "stack" && "$2" == "post-config" ]]; then
        echo_summary "Configuring Tricircle"

        configure_tricircle_api

        echo export PYTHONPATH=\$PYTHONPATH:$TRICIRCLE_DIR >> $RC_DIR/.localrc.auto

        recreate_database tricircle
        python "$TRICIRCLE_DIR/cmd/manage.py" "$TRICIRCLE_API_CONF"

    elif [[ "$1" == "stack" && "$2" == "extra" ]]; then
        echo_summary "Initializing Tricircle Service"

        if is_service_enabled t-api; then

            create_tricircle_accounts

            run_process t-api "python $TRICIRCLE_API --config-file $TRICIRCLE_API_CONF"
        fi
    fi

    if [[ "$1" == "unstack" ]]; then

        if is_service_enabled t-api; then
           stop_process t-api
        fi
    fi
fi
