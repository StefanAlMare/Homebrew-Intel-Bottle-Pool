# Optional bash/zsh integration. Source after brew-pool has been added to PATH.
# Identity: StefanAlMare. Only stable/default-option upgrade routines are routed.
brew() {
    case "${1-}" in
        update)
            command brew "$@" || return "$?"
            command brew-pool sync || :
            ;;
        upgrade)
            shift
            if [ "${1-}" = "--formula" ] || [ "${1-}" = "--formulae" ]; then
                shift
                command brew-pool upgrade --no-casks "$@"
            else
                command brew-pool upgrade "$@"
            fi
            ;;
        *) command brew "$@" ;;
    esac
}
